"""Migrations target the URL the caller provides, not the OS env / the default.

Regression test for the env.py bug where the caller-provided ``sqlalchemy.url``
was overwritten with the Alembic ``DATABASE_URL`` option (which carried a
built-in default), so migrations ran against the wrong database when
``DATABASE_URL`` was set.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from server.migrations.utils.db_utils import upgrade_db

# Repo's apps/ dir: alembic.ini uses ``script_location = server/migrations``,
# resolved relative to CWD, so migrations only load from there.
_APPS_DIR = Path(__file__).parents[3]


@pytest.fixture(autouse=True)
def _chdir_to_apps(monkeypatch):
    """Run alembic from apps/ so the relative script_location resolves, the way
    the app does at runtime."""
    monkeypatch.chdir(_APPS_DIR)


def _table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_uses_passed_url_over_env(make_database, monkeypatch):
    """An explicit db_url wins even when OS DATABASE_URL points elsewhere."""
    target_url = make_database("migrations_explicit")
    decoy_url = make_database("migrations_from_env")
    # OS env points at the decoy; the explicit argument must take precedence.
    monkeypatch.setenv("DATABASE_URL", decoy_url)

    upgrade_db(target_url)

    # The passed-in database got the schema...
    assert "users" in _table_names(target_url)
    # ...and the env-pointed decoy was never touched (not even alembic_version).
    assert _table_names(decoy_url) == set()


def test_upgrade_honours_env_when_no_explicit_url(make_database, monkeypatch):
    """With no caller URL on the config, the OS env DATABASE_URL is used.

    Drives Alembic the way the CLI would (fresh Config from alembic.ini), so the
    only URL source is the environment.
    """
    from alembic import command
    from alembic.config import Config

    env_url = make_database("migrations_from_os_env")
    monkeypatch.setenv("DATABASE_URL", env_url)

    ini = _APPS_DIR / "server" / "alembic.ini"
    cfg = Config(str(ini))
    # Note: sqlalchemy.url left as the ini's %(DATABASE_URL)s placeholder, so
    # env.py must fall back to the OS env to resolve it.
    command.upgrade(cfg, "head")

    assert "users" in _table_names(env_url)


def test_migrations_match_the_models(make_database):
    """`alembic check` through env.py: no diff between the migrated schema and
    the models. An env.py that forgets to import the models sees an empty
    metadata and reports every table as one to drop."""
    from alembic import command
    from alembic.config import Config

    url = make_database("migrations_check")
    upgrade_db(url)

    cfg = Config(str(_APPS_DIR / "server" / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", url)
    command.check(cfg)


def test_qa_pairs_key_is_scoped_to_the_dataset(make_database):
    """Autogenerate does not compare primary keys, so check this one directly."""
    url = make_database("migrations_qa_pk")
    upgrade_db(url)

    engine = create_engine(url)
    try:
        pk = inspect(engine).get_pk_constraint("qa_pairs")
    finally:
        engine.dispose()
    assert pk["constrained_columns"] == ["dataset_id", "id"]


def test_upgrade_never_logs_the_database_url(make_database, caplog):
    """The URL carries the database password; it must not reach any handler."""
    import logging

    from sqlalchemy import make_url

    url = make_database("migrations_no_url_log")
    caplog.set_level(logging.DEBUG)

    upgrade_db(url)

    assert url not in caplog.text
    password = make_url(url).password
    if password:
        assert password not in caplog.text
