"""Migrations target the URL the caller provides, not the OS env / sqlite default.

Regression test for the env.py bug where the caller-provided ``sqlalchemy.url``
was overwritten with the Alembic ``DATABASE_URL`` option (defaulting to sqlite),
so migrations ran against the wrong database when ``DATABASE_URL`` was set.
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


def test_upgrade_uses_passed_url_over_env(tmp_path, monkeypatch):
    """An explicit db_url wins even when OS DATABASE_URL points elsewhere."""
    target = tmp_path / "explicit.db"
    decoy = tmp_path / "from_env.db"
    # OS env points at the decoy; the explicit argument must take precedence.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{decoy}")

    upgrade_db(f"sqlite:///{target}")

    # The passed-in database got the schema...
    assert target.exists()
    assert "datasets" in _table_names(f"sqlite:///{target}")
    # ...and the env-pointed decoy was never touched.
    assert not decoy.exists()


def test_upgrade_honours_env_when_no_explicit_url(tmp_path, monkeypatch):
    """With no caller URL on the config, the OS env DATABASE_URL is used.

    Drives Alembic the way the CLI would (fresh Config from alembic.ini), so the
    only URL source is the environment.
    """
    from alembic import command
    from alembic.config import Config

    env_db = tmp_path / "env.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{env_db}")

    ini = _APPS_DIR / "server" / "alembic.ini"
    cfg = Config(str(ini))
    # Note: sqlalchemy.url left as the ini's %(DATABASE_URL)s placeholder, so
    # env.py must fall back to the OS env to resolve it.
    command.upgrade(cfg, "head")

    assert env_db.exists()
    assert "datasets" in _table_names(f"sqlite:///{env_db}")
