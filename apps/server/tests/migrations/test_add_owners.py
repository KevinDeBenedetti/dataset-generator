"""a8b9c0d1e2f3: legacy rows get an owner, nothing is deleted, downgrade works.

Needs a real Postgres (the migration uses regexp_replace, partial indexes and
constraint swaps): it runs with the rest of the suite via ``make test``.
"""

import datetime as dt
from pathlib import Path
from urllib.parse import quote

import pytest
from alembic import command
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Integer,
    MetaData,
    Table,
    create_engine,
    inspect,
    select,
    text,
)

from server.migrations.utils.db_utils import get_alembic_config

_SCRIPTS = Path(__file__).parents[2] / "migrations"
BEFORE, AFTER = "f6a7b8c9d0e1", "a8b9c0d1e2f3"
SYSTEM_EMAIL = "system@datasetgen.invalid"

# A lock wait or a stuck statement must fail the test with a message, never hang
# the suite: a migration test that blocks would otherwise stall CI for hours.
_TIMEOUTS = "-c lock_timeout=15000 -c statement_timeout=60000"


def _cfg(url):
    """Alembic config for ``url`` with an absolute script location (independent
    of the working directory) and bounded waits."""
    separator = "&" if "?" in url else "?"
    # "%" is configparser's interpolation character: double it in the ini value.
    options = quote(_TIMEOUTS).replace("%", "%%")
    config = get_alembic_config(f"{url}{separator}options={options}")
    config.set_main_option("script_location", str(_SCRIPTS))
    return config


@pytest.fixture
def make_engine():
    engines = []

    def make(url):
        engine = create_engine(url, connect_args={"options": _TIMEOUTS})
        engines.append(engine)
        return engine

    yield make
    for engine in engines:
        engine.dispose()


def _filler(column):
    kind = column.type
    if isinstance(kind, Boolean):
        return False
    if isinstance(kind, (Integer, Float)):
        return 0
    if isinstance(kind, DateTime):
        return dt.datetime(2026, 1, 1)
    if isinstance(kind, JSON):
        return {}
    return "x"


def _insert(engine, table_name, **values):
    """Insert a row, filling every other required column with a dummy value."""
    table = Table(table_name, MetaData(), autoload_with=engine)
    row = {
        c.name: values.get(c.name, _filler(c))
        for c in table.columns
        if c.name in values or (not c.nullable and c.server_default is None)
    }
    with engine.begin() as conn:
        conn.execute(table.insert().values(**row))


@pytest.fixture
def legacy_db(make_database):
    """A database at the revision before the migration, holding legacy rows."""
    url = make_database("migrations_owners")
    command.upgrade(_cfg(url), BEFORE)
    return url


def _seed_legacy(engine):
    _insert(engine, "datasets", id="d1", name="My Data/Set")
    _insert(engine, "datasets", id="d2", name="plain")
    _insert(engine, "job_runs", id="r1", job_id="github-personal", status="succeeded")
    _insert(engine, "model_defaults", role="qa", model_ref="openai:m")
    _insert(engine, "quality_rules", id="default", min_answer_words=9)


def _owners(engine, table, column="owner_id"):
    with engine.connect() as conn:
        return set(conn.execute(text(f"SELECT {column} FROM {table}")).scalars())


def test_without_an_admin_legacy_rows_go_to_an_inactive_system_user(
    legacy_db, make_engine
):
    engine = make_engine(legacy_db)
    _seed_legacy(engine)

    command.upgrade(_cfg(legacy_db), AFTER)

    with engine.connect() as conn:
        system = conn.execute(
            text("SELECT id, is_active, hashed_password FROM users WHERE email = :e"),
            {"e": SYSTEM_EMAIL},
        ).one()
    assert system.is_active is False and system.hashed_password is None
    for table in ("datasets", "job_runs"):
        assert _owners(engine, table) == {system.id}
    assert _owners(engine, "model_defaults", "user_id") == {system.id}
    assert _owners(engine, "quality_rules", "user_id") == {system.id}
    with engine.connect() as conn:
        # Nothing was lost, and each dataset keeps the collection it already had.
        collections = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT id, qdrant_collection FROM datasets"))
        }
    assert collections == {"d1": "dataset_my_data_set", "d2": "dataset_plain"}


def test_with_an_admin_legacy_rows_go_to_the_oldest_active_admin(
    legacy_db, make_engine
):
    engine = make_engine(legacy_db)
    _insert(
        engine,
        "users",
        id="late",
        email="late@x.io",
        role="admin",
        is_active=True,
        created_at=dt.datetime(2026, 5, 1),
    )
    _insert(
        engine,
        "users",
        id="first",
        email="first@x.io",
        role="admin",
        is_active=True,
        created_at=dt.datetime(2026, 1, 1),
    )
    _insert(
        engine,
        "users",
        id="off",
        email="off@x.io",
        role="admin",
        is_active=False,
        created_at=dt.datetime(2025, 1, 1),
    )
    _seed_legacy(engine)

    command.upgrade(_cfg(legacy_db), AFTER)

    assert _owners(engine, "datasets") == {"first"}
    assert _owners(engine, "job_runs") == {"first"}
    with engine.connect() as conn:
        assert not conn.execute(
            text("SELECT 1 FROM users WHERE email = :e"), {"e": SYSTEM_EMAIL}
        ).first()  # no placeholder needed


def test_a_fresh_database_gets_no_system_user(legacy_db, make_engine):
    command.upgrade(_cfg(legacy_db), AFTER)

    engine = make_engine(legacy_db)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 0


def test_the_same_name_is_now_allowed_for_two_owners_but_not_twice_for_one(
    legacy_db, make_engine
):
    from sqlalchemy.exc import IntegrityError

    command.upgrade(_cfg(legacy_db), AFTER)
    engine = make_engine(legacy_db)
    _insert(engine, "users", id="a", email="a@x.io")
    _insert(engine, "users", id="b", email="b@x.io")
    _insert(engine, "datasets", id="1", name="same", owner_id="a")
    _insert(engine, "datasets", id="2", name="same", owner_id="b")
    with pytest.raises(IntegrityError):
        _insert(engine, "datasets", id="3", name="same", owner_id="a")


def test_downgrade_restores_the_previous_shape_and_keeps_the_rows(
    legacy_db, make_engine
):
    engine = make_engine(legacy_db)
    _seed_legacy(engine)
    cfg = _cfg(legacy_db)
    command.upgrade(cfg, AFTER)

    command.downgrade(cfg, BEFORE)

    columns = {c["name"] for c in inspect(engine).get_columns("datasets")}
    assert "owner_id" not in columns and "qdrant_collection" not in columns
    assert {c["name"] for c in inspect(engine).get_columns("quality_rules")} >= {"id"}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM datasets")).scalar() == 2
        assert (
            conn.execute(select(text("min_answer_words FROM quality_rules"))).scalar()
            == 9
        )
