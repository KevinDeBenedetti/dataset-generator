"""The remote SQL connector (connectors/sql_remote.py) against a fake psycopg
connection: only admin-allowed, public hosts; TLS verified, a read-only
session and a timeout; named columns, never SQL; the password nowhere."""

import asyncio
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from server.connectors.base import ConnectorError, Limits
from server.connectors.sql_remote import SqlRemoteConfig, SqlRemoteConnector
from server.tests.creds import NONE

CONFIG = {
    "host": "db.example.org",
    "database": "opendata",
    "user": "reader",
    "schema": "public",
    "table": "communes",
    "columns": ["code", "nom"],
    "max_rows": 3,
}
PASSWORD = "pw-" + "s" * 20
ROWS = [
    ("29019", "Brest"),
    ("29232", "Quimper"),
    ("56121", "Lorient"),
    ("22278", "Saint-Brieuc"),
]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [SimpleNamespace(name="code"), SimpleNamespace(name="nom")]
        self.itersize = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        text = query.as_string(None)
        self.conn.queries.append(text)
        limit = int(text.rsplit("LIMIT", 1)[1])
        self._rows = list(ROWS[:limit])

    def fetchmany(self, n):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out


class FakeConn:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.read_only = False
        self.queries = []
        self.closed = False

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self, name=None):
        assert name, "rows are read with a server-side cursor"
        return FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def db(monkeypatch):
    made = []

    def connect(**kwargs):
        conn = FakeConn(**kwargs)
        made.append(conn)
        return conn

    monkeypatch.setattr("psycopg.connect", connect)
    monkeypatch.setattr(
        "server.services.platform.allowed_sql_hosts", lambda: ["db.example.org"]
    )
    monkeypatch.setattr("server.core.net.resolve_sync", lambda host, port: ["5.6.7.8"])
    monkeypatch.setattr(
        "server.services.user_secrets.get_source_secret", lambda owner, kind: PASSWORD
    )
    return made


def _fetch(tmp_path, config=CONFIG):
    return asyncio.run(
        SqlRemoteConnector().fetch(
            "alice", "0" * 32, config, NONE, tmp_path, Limits(10**8, timeout_s=60)
        )
    )


def test_a_table_is_read_read_only_over_verified_tls(db, tmp_path):
    result = _fetch(tmp_path)
    [conn] = db
    kwargs = conn.kwargs
    assert kwargs["hostaddr"] == "5.6.7.8" and kwargs["host"] == "db.example.org"
    assert kwargs["sslmode"] == "verify-full" and kwargs["sslrootcert"] == "system"
    assert "default_transaction_read_only=on" in kwargs["options"]
    assert "statement_timeout=60000" in kwargs["options"]
    assert conn.read_only is True and conn.closed
    assert conn.queries == ['SELECT "code", "nom" FROM "public"."communes" LIMIT 4']
    table = pq.read_table(result.files[0])
    assert table.num_rows == 3 and table.column_names == ["code", "nom"]
    assert result.warnings == ["Stopped at 3 rows (max_rows)"]
    assert PASSWORD not in str(result.provenance.to_dict())


def test_no_allowed_host_refuses_every_database(db, tmp_path, monkeypatch):
    monkeypatch.setattr("server.services.platform.allowed_sql_hosts", lambda: [])
    with pytest.raises(ConnectorError, match="allowed_sql_hosts"):
        _fetch(tmp_path)
    assert db == []


def test_a_host_not_allowed_or_private_is_refused(db, tmp_path, monkeypatch):
    with pytest.raises(ConnectorError, match="not an allowed host"):
        _fetch(tmp_path, {**CONFIG, "host": "other.example.org"})
    monkeypatch.setattr("server.core.net.resolve_sync", lambda host, port: ["10.0.0.5"])
    with pytest.raises(ConnectorError, match="non-public"):
        _fetch(tmp_path)
    assert db == []


def test_names_are_names_not_sql():
    for bad in (
        {"table": "communes; DROP TABLE x"},
        {"columns": ["nom FROM x --"]},
        {"schema": "public.x"},
        {"host": "postgres://db.example.org:5432"},
    ):
        with pytest.raises(ValueError):
            SqlRemoteConfig.model_validate({**CONFIG, **bad})


def test_a_refusal_never_shows_the_password(db, tmp_path, monkeypatch):
    import psycopg

    def refuse(**kwargs):
        raise psycopg.OperationalError(
            f"password authentication failed ({kwargs['password']})"
        )

    monkeypatch.setattr("psycopg.connect", refuse)
    with pytest.raises(ConnectorError) as raised:
        _fetch(tmp_path)
    assert PASSWORD not in str(raised.value) and "***" in str(raised.value)


def test_the_password_is_the_data_sources_secret(test_db, client_for):
    from server.services.users import create_user

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    api = client_for(alice, real_credentials=True)
    source = api.post(
        "/data-sources",
        json={"name": "Ma base", "connector": "sql_remote", "config": CONFIG},
    )
    assert source.status_code == 201, source.text
    assert "password" not in source.json()["config"]
    saved = api.put(
        f"/data-sources/{source.json()['id']}/secret", json={"value": PASSWORD}
    )
    assert saved.status_code == 200 and saved.json() == {"configured": True}


def test_more_bytes_than_allowed_stop_the_read(db, tmp_path):
    with pytest.raises(ConnectorError, match="MB of rows"):
        asyncio.run(
            SqlRemoteConnector().fetch(
                "alice", "0" * 32, CONFIG, NONE, tmp_path, Limits(10, timeout_s=60)
            )
        )
