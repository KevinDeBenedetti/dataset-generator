import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context
from server.core.database import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.
def _resolve_db_url() -> str:
    """Resolve the database URL migrations run against, with precedence:

    1. A URL the caller already injected into the Alembic config
       (``db_utils.upgrade_db`` / ``get_alembic_config`` set ``sqlalchemy.url``)
       — so an explicit argument (tests, ``reset_db``) wins.
    2. The OS env ``DATABASE_URL`` — so a deployed Postgres is honoured when
       alembic is driven directly from the CLI.
    3. The sqlite dev default.

    Previously this read the Alembic *option* ``DATABASE_URL`` (never the OS
    env) and overwrote the caller's ``sqlalchemy.url`` with the sqlite default,
    so migrations silently ran against the wrong database when ``DATABASE_URL``
    was set.
    """
    try:
        existing = config.get_main_option("sqlalchemy.url")
    except Exception:
        # Unresolved ``%(DATABASE_URL)s`` interpolation from alembic.ini.
        existing = None
    return existing or os.environ.get("DATABASE_URL") or "sqlite:///./datasets.db"


config.set_main_option("sqlalchemy.url", _resolve_db_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
