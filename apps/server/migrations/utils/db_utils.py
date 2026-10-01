# myapp/db_utils.py
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
import logging
from pathlib import Path
import os
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# Arbitrary app-wide constant: the Postgres advisory lock that serialises
# migration runs (several pods starting together must not race Alembic).
MIGRATION_LOCK_KEY = 727_201

DEFAULT_PATH = Path(__file__).parent.parent.parent / "alembic.ini"


def get_alembic_config(db_url: str | None = None, path: Path = DEFAULT_PATH) -> Config:
    """
    Loads the Alembic configuration and replaces the database URL if needed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Alembic config file not found at {path}")
    cfg_path = str(path)
    alembic_cfg = Config(cfg_path)
    # Keep the app's logging setup (see migrations/env.py).
    alembic_cfg.attributes["configure_logger"] = False

    alembic_cfg.set_main_option("script_location", "migrations")

    # Explicitly set sqlalchemy.url to avoid interpolation errors
    if db_url:
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    else:
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            alembic_cfg.set_main_option("sqlalchemy.url", env_url)
        else:
            # Empty value to prevent configparser from attempting interpolation on %(DATABASE_URL)s
            alembic_cfg.set_main_option("sqlalchemy.url", "")

    return alembic_cfg


def is_migration_needed(db_url: str, revision: str = "head") -> bool:
    """
    Quickly checks if migrations are needed.
    """
    try:
        cfg = get_alembic_config(db_url)

        # Create a temporary connection
        engine = create_engine(db_url)

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_rev = context.get_current_revision()

            # Get the head revision
            script = ScriptDirectory.from_config(cfg)
            head_rev = script.get_current_head()

            logger.debug(f"Current revision: {current_rev}, Head revision: {head_rev}")

            # If current_rev is None, the database is not initialized
            if current_rev is None:
                logger.debug("Database not initialized, migration needed")
                return True

            # If revisions are different, migration is needed
            needs_migration = current_rev != head_rev
            logger.debug(f"Migration needed: {needs_migration}")
            return needs_migration

    except Exception as e:
        logger.debug(f"Error during verification, migration needed: {e}")
        return True  # In case of error, assume migration is needed


def upgrade_db(db_url: str, revision: str = "head") -> None:
    """Applies Alembic migrations."""
    # Ensure the path to alembic.ini is correct
    config_path = Path(__file__).parent.parent.parent / "alembic.ini"
    if not config_path.exists():
        logger.error(f"alembic.ini file not found: {config_path}")
        raise FileNotFoundError(f"alembic.ini not found at {config_path}")

    logger.debug(f"Using Alembic config file at {config_path}")
    cfg = Config(str(config_path))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", db_url)
    logger.debug("Upgrading database to revision %s", revision)
    # A session-level advisory lock on a dedicated connection: a second process
    # blocks here until the first has finished, then finds nothing left to do.
    # (Not usable through a transaction-pooling proxy — migrate on a direct URL.)
    lock_engine = create_engine(db_url) if db_url.startswith("postgresql") else None
    lock_conn = lock_engine.connect() if lock_engine is not None else None
    try:
        if lock_conn is not None:
            logger.debug("Waiting for the migration advisory lock")
            lock_conn.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            lock_conn.commit()
        command.upgrade(cfg, revision)
    finally:
        if lock_conn is not None:
            try:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
                )
                lock_conn.commit()
            finally:
                lock_conn.close()
        if lock_engine is not None:
            lock_engine.dispose()
    logger.info("Database migrated to %s", revision)


def downgrade_db(db_url: str | None = None, revision: str = "base"):
    """
    Rolls back to the specified revision (default 'base').
    db_url must be passed first (positional or named).
    """
    cfg = get_alembic_config(db_url)
    command.downgrade(cfg, revision)
    logger.info(f"Database downgraded to {revision}")


def reset_db(db_url: str):
    """
    Restores a clean database by redoing all migrations from scratch.
    db_url must be passed first (positional or named).
    """
    downgrade_db(db_url, "base")
    upgrade_db(db_url, "head")
    logger.info("Database reset successfully.")
