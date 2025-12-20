# myapp/db_utils.py
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
import logging
from pathlib import Path
import os
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

DEFAULT_PATH = Path(__file__).parent.parent.parent / "alembic.ini"


def get_alembic_config(db_url: str | None = None, path: Path = DEFAULT_PATH) -> Config:
    """
    Loads the Alembic configuration and replaces the database URL if needed.
    """
    if not path.exists():
        raise FileNotFoundError(f"Alembic config file not found at {path}")
    cfg_path = str(path)
    alembic_cfg = Config(cfg_path)

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
    cfg.set_main_option("sqlalchemy.url", db_url)
    logger.debug(f"Upgrading database to revision {revision}")
    logger.debug(f"Database URL: {db_url}")
    try:
        command.upgrade(cfg, revision)
        logger.info(f"Database migrated to {revision}")
    except Exception as e:
        logger.warning(
            "Alembic execution failed, fallback: creating tables via SQLAlchemy"
        )
        raise e


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
