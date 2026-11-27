"""The SQL dump connector (connectors/sql_dump.py): Postgres and MySQL dumps
load into a sandboxed DuckDB; a dangerous statement is refused before anything
runs; the app's database is never touched."""

import asyncio
import gzip
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from server.connectors.base import ConnectorError, Limits
from server.services.credentials import Credentials
from server.connectors.sql_dump import (
    SqlDumpConnector,
    describe,
    detect_dialect,
    load_dump,
    plan,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sql"
LIMITS = Limits(max_bytes=10 * 1024 * 1024, timeout_s=60)


def _rows(session, sql):
    return session.fetchall(sql)


def test_a_postgres_dump_loads_with_its_copy_data(tmp_path):
    path = FIXTURES / "communes_pg.sql"
    assert detect_dialect(path.read_text()) == "postgres"
    session, dialect, tables = load_dump(path, tmp_path / "w", LIMITS)
    try:
        assert {t.name: t.rows for t in tables} == {"communes": 4, "regions": 3}
        rows = _rows(
            session, "SELECT code, nom, population, maj FROM communes ORDER BY code"
        )
        assert rows[0][0] == "29019" and rows[0][2] == 139456
        quimper = [r for r in rows if r[0] == "29232"][0]
        assert quimper[3] is None  # \N
        escaped = [r for r in rows if r[0] == "29103"][0]
        assert escaped[1] == "C:\\dossier\ttab"
        assert [r for r in rows if r[0] == "56121"][0][1] == 'Lorient; "port"'
    finally:
        session.close()


def test_a_mysql_dump_loads(tmp_path):
    path = FIXTURES / "communes_mysql.sql"
    assert detect_dialect(path.read_text()) == "mysql"
    session, _, tables = load_dump(path, tmp_path / "w", LIMITS)
    try:
        assert [(t.name, t.rows) for t in tables] == [("communes", 3)]
        rows = _rows(
            session, "SELECT nom, population FROM communes WHERE code = '29232'"
        )
        assert rows == [("L'Île; Tudy", None)]
    finally:
        session.close()


def test_a_gzipped_dump_loads(tmp_path):
    path = tmp_path / "dump.sql.gz"
    path.write_bytes(gzip.compress((FIXTURES / "communes_mysql.sql").read_bytes()))
    config = describe(path, "dump.sql.gz", tmp_path / "w", LIMITS)
    assert config["dialect"] == "mysql" and config["table"] == "communes"


@pytest.mark.parametrize(
    "statement",
    [
        "DROP DATABASE prod;",
        "DROP SCHEMA public CASCADE;",
        "COPY public.communes TO PROGRAM 'curl example.com';",
        "COPY public.communes TO '/tmp/out.csv';",
        "COPY public.communes FROM PROGRAM 'cat /etc/passwd';",
        "COPY public.communes FROM '/etc/passwd';",
        "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;",
        "CREATE EXTENSION postgis;",
        "ATTACH '/data/app.db' AS app;",
        "INSTALL httpfs;",
        "CREATE TABLE copy AS SELECT * FROM read_csv('/etc/passwd');",
        "INSERT INTO regions SELECT * FROM read_text('/etc/passwd');",
        "INSERT INTO regions VALUES (1, read_text('/etc/passwd'));",
        "\\! rm -rf /",
    ],
)
def test_a_dangerous_statement_is_refused_before_anything_runs(statement):
    dump = (FIXTURES / "communes_pg.sql").read_text() + "\n" + statement + "\n"
    with pytest.raises(ConnectorError):
        plan(dump, "postgres")


def test_a_custom_format_archive_says_how_to_export(tmp_path):
    path = tmp_path / "dump.sql"
    path.write_bytes(b"PGDMP\x01\x0e\x00")
    with pytest.raises(ConnectorError, match="-Fp"):
        load_dump(path, tmp_path / "w", LIMITS)


def test_a_dump_too_large_once_decompressed_is_refused(tmp_path):
    path = tmp_path / "dump.sql.gz"
    path.write_bytes(gzip.compress(b"-- " + b"x" * 5000))
    with pytest.raises(ConnectorError, match="decompressed"):
        load_dump(path, tmp_path / "w", Limits(max_bytes=1000))


def test_the_run_never_connects_to_the_app_database(tmp_path, monkeypatch):
    """The whole fetch with every way to the app's database made to fail."""
    from server.core import database
    from server.services.draft_store import SOURCES_DIR, DraftStore

    def refuse(*args, **kwargs):
        raise AssertionError("the SQL dump connector opened the app's database")

    for name in ("get_db", "get_scoped_db", "SessionLocal"):
        if hasattr(database, name):
            monkeypatch.setattr(database, name, refuse)
    monkeypatch.setattr(database.engine, "connect", refuse)
    monkeypatch.setattr(database.engine, "raw_connection", refuse)

    store = DraftStore(tmp_path / "store")
    monkeypatch.setattr("server.services.draft_store.get_store", lambda: store)
    stored = store.path("alice", SOURCES_DIR, "s1", "communes_pg.sql")
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes((FIXTURES / "communes_pg.sql").read_bytes())
    config = describe(stored, "communes_pg.sql", tmp_path / "describe", LIMITS)
    assert config["table"] is None  # two tables: the user picks one
    config["table"] = "regions"
    result = asyncio.run(
        SqlDumpConnector().fetch(
            "alice", "s1", config, Credentials(), tmp_path / "run", LIMITS
        )
    )
    table = pq.read_table(result.files[0])
    assert table.num_rows == 3 and table.column_names == ["id", "nom"]
    assert result.format == "parquet" and result.version == config["sha256"]


def test_no_table_picked_names_the_choices(tmp_path, monkeypatch):
    from server.services.draft_store import SOURCES_DIR, DraftStore

    store = DraftStore(tmp_path / "store")
    monkeypatch.setattr("server.services.draft_store.get_store", lambda: store)
    stored = store.path("alice", SOURCES_DIR, "s1", "communes_pg.sql")
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes((FIXTURES / "communes_pg.sql").read_bytes())
    config = describe(stored, "communes_pg.sql", tmp_path / "describe", LIMITS)
    with pytest.raises(ConnectorError, match="communes, regions"):
        asyncio.run(
            SqlDumpConnector().fetch(
                "alice", "s1", config, Credentials(), tmp_path / "run", LIMITS
            )
        )


def test_uploading_a_dump_makes_a_sql_dump_source(test_db, client_for):
    from server.services.users import create_user

    alice = create_user(test_db, email="alice@test.local", password="pw12345")
    api = client_for(alice, real_credentials=True)
    resp = api.post(
        "/data-sources/upload",
        files={"file": ("communes.sql", (FIXTURES / "communes_pg.sql").read_bytes())},
        data={"name": "Communes"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["connector"] == "sql_dump" and body["config"]["dialect"] == "postgres"
    assert [t["name"] for t in body["config"]["tables"]] == ["communes", "regions"]
    picked = api.patch(
        f"/data-sources/{body['id']}",
        json={"config": {**body["config"], "table": "communes"}},
    )
    assert picked.status_code == 200 and picked.json()["config"]["table"] == "communes"
    refused = api.post(
        "/data-sources/upload",
        files={"file": ("bad.sql", b"DROP DATABASE prod;\n")},
        data={"name": "Bad"},
    )
    assert refused.status_code == 422, refused.text
    assert "DROP DATABASE" in refused.json()["detail"]
    recipe = api.post(
        "/recipes",
        json={
            "name": "Communes",
            "data_source_id": body["id"],
            "target_repo": "alice/communes",
        },
    ).json()
    preview = api.post(f"/recipes/{recipe['id']}/preview", json={}).json()
    assert preview["source_rows"] == 4, preview
    assert [c["name"] for c in preview["schema"]][:3] == ["code", "nom", "population"]


def test_pg_dump_meta_commands_are_skipped_and_others_refused():
    dump = (FIXTURES / "communes_pg.sql").read_text()
    restricted = "\\restrict abc123\n" + dump + "\n\\unrestrict abc123\n"
    assert any(kind == "copy" for kind, _ in plan(restricted, "postgres"))
    for line in ("\\! rm -rf /", "-- a comment\n\\o /tmp/out", "\\copy t to '/tmp/x'"):
        with pytest.raises(ConnectorError, match="psql command"):
            plan(dump + "\n" + line + "\n", "postgres")


def test_an_unterminated_quote_or_comment_reads_in_linear_time():
    import time

    start = time.monotonic()
    # The comment runs to the end: only the CREATE TABLE is left.
    assert len(plan("CREATE TABLE t (a int);\n" + "/* '" * 200_000, "mysql")) == 1
    with pytest.raises(ConnectorError, match="not loaded"):
        plan("CREATE TABLE t (a int);\n" + "'/*" * 200_000, "postgres")
    assert time.monotonic() - start < 5
