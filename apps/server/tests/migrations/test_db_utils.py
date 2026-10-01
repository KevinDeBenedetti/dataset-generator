"""upgrade_db serialises concurrent migration runs with a Postgres advisory lock."""

from unittest.mock import MagicMock, patch

import pytest

from server.migrations.utils import db_utils
from server.migrations.utils.db_utils import MIGRATION_LOCK_KEY, upgrade_db


def _engine_recording(calls):
    engine = MagicMock()
    connection = MagicMock()

    def execute(statement, params=None):
        calls.append(("sql", str(statement), params))

    connection.execute.side_effect = execute
    connection.close.side_effect = lambda: calls.append(("conn.close",))
    engine.connect.return_value = connection
    engine.dispose.side_effect = lambda: calls.append(("engine.dispose",))
    return engine


def _sql(calls):
    return [c[1] for c in calls if c[0] == "sql"]


def test_postgres_upgrade_runs_between_lock_and_unlock():
    calls = []
    with (
        patch.object(db_utils, "create_engine", return_value=_engine_recording(calls)),
        patch.object(
            db_utils.command,
            "upgrade",
            side_effect=lambda *a: calls.append(("upgrade",)),
        ),
    ):
        upgrade_db("postgresql+psycopg://u:p@db/app")

    kinds = [c[0] if c[0] != "sql" else c[1] for c in calls]
    assert kinds[0].startswith("SELECT pg_advisory_lock")
    assert kinds[1] == "upgrade"
    assert kinds[2].startswith("SELECT pg_advisory_unlock")
    assert kinds[-2:] == ["conn.close", "engine.dispose"]
    assert all(c[2] == {"key": MIGRATION_LOCK_KEY} for c in calls if c[0] == "sql")


def test_lock_is_released_when_the_migration_fails():
    calls = []
    with (
        patch.object(db_utils, "create_engine", return_value=_engine_recording(calls)),
        patch.object(db_utils.command, "upgrade", side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            upgrade_db("postgresql+psycopg://u:p@db/app")

    assert any("pg_advisory_unlock" in sql for sql in _sql(calls))
    assert ("conn.close",) in calls


def test_non_postgres_urls_take_no_lock():
    with (
        patch.object(db_utils, "create_engine") as create_engine,
        patch.object(db_utils.command, "upgrade") as upgrade,
    ):
        upgrade_db("sqlite:///x.db")

    create_engine.assert_not_called()
    upgrade.assert_called_once()
