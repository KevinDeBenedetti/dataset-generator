"""5d6e7f8091a2: one LLM per user, and the Claude secrets are gone.

Needs a real Postgres: it runs with the rest of the suite via ``make test``.
"""

import datetime as dt

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from server.tests.migrations.test_add_owners import _bound_waits, _cfg, _insert

BEFORE, AFTER = "4c5d6e7f8091", "5d6e7f8091a2"
WHEN = dt.datetime(2026, 1, 1)


@pytest.fixture
def before(make_database):
    """A database at the revision before the migration, with three users:
    its URL and an engine on it."""
    url = make_database("migrations_one_llm")
    _bound_waits(url)
    command.upgrade(_cfg(url), BEFORE)
    engine = create_engine(url)
    for user_id in ("u1", "u2", "u3"):
        _insert(
            engine,
            "users",
            id=user_id,
            email=f"{user_id}@x.io",
            role="user",
            is_active=True,
            created_at=WHEN,
        )
    yield url, engine
    engine.dispose()


def _default(engine, user_id, role, ref):
    _insert(
        engine,
        "model_defaults",
        user_id=user_id,
        role=role,
        model_ref=ref,
        updated_at=WHEN,
    )


def _rows(engine, query):
    with engine.connect() as conn:
        return sorted(tuple(row) for row in conn.execute(text(query)))


def test_each_user_keeps_one_llm_and_the_claude_secrets_go(before):
    url, engine = before
    _default(engine, "u1", "cleaning", "openai:clean")
    _default(engine, "u1", "qa", "openai:qa")  # the Q&A model wins
    _default(engine, "u2", "qa", "claude:claude-sonnet-5-5")  # Claude is gone
    _default(engine, "u2", "jobs", "openai:jobs")
    _default(engine, "u3", "qa", "claude:x")  # nothing left: OPENAI_LLM_MODEL
    for user_id, kind in (
        ("u1", "claude_token"),
        ("u1", "openai_api_key"),
        ("u2", "anthropic_api_key"),
    ):
        _insert(engine, "user_secrets", user_id=user_id, kind=kind, updated_at=WHEN)

    command.upgrade(_cfg(url), AFTER)

    assert _rows(engine, "SELECT user_id, role, model_ref FROM model_defaults") == [
        ("u1", "llm", "openai:qa"),
        ("u2", "llm", "openai:jobs"),
    ]
    assert _rows(engine, "SELECT user_id, kind FROM user_secrets") == [
        ("u1", "openai_api_key")
    ]


def test_the_downgrade_gives_every_step_the_llm(before):
    url, engine = before
    command.upgrade(_cfg(url), AFTER)
    _default(engine, "u1", "llm", "openai:m")

    command.downgrade(_cfg(url), BEFORE)

    assert _rows(engine, "SELECT role, model_ref FROM model_defaults") == [
        ("cleaning", "openai:m"),
        ("jobs", "openai:m"),
        ("qa", "openai:m"),
        ("vision", "openai:m"),
    ]
