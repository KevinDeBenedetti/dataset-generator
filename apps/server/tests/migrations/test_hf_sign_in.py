"""b3c4d5e6f7a8 (users' HF identity) and c4d5e6f7a8b9 (the sign-up policy).

Needs a real Postgres: it runs with the rest of the suite via ``make test``.
"""

import datetime as dt

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from server.tests.migrations.test_add_owners import _bound_waits, _cfg, _insert

BEFORE, HF, POLICY = "a2b3c4d5e6f7", "b3c4d5e6f7a8", "c4d5e6f7a8b9"
WHEN = dt.datetime(2026, 1, 1)


@pytest.fixture
def before(make_database):
    url = make_database("migrations_hf_sign_in")
    _bound_waits(url)
    command.upgrade(_cfg(url), BEFORE)
    engine = create_engine(url)
    _insert(
        engine,
        "users",
        id="u1",
        email="u1@x.io",
        role="user",
        is_active=True,
        created_at=WHEN,
    )
    yield url, engine
    engine.dispose()


def _setting(engine, key):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key}
        ).first()
    return None if row is None else row[0]


def test_users_get_an_hf_identity_and_may_have_no_email(before):
    url, engine = before
    command.upgrade(_cfg(url), HF)
    _insert(engine, "users", id="u2", email=None, hf_id="hf-2", role="user")
    _insert(engine, "users", id="u3", email=None, hf_id="hf-3", role="user")
    with pytest.raises(IntegrityError):
        _insert(engine, "users", id="u4", email=None, hf_id="hf-3", role="user")

    command.downgrade(_cfg(url), BEFORE)
    with engine.connect() as conn:
        emails = sorted(r[0] for r in conn.execute(text("SELECT email FROM users")))
    assert emails == [
        "hf-u2@hf-account.invalid",
        "hf-u3@hf-account.invalid",
        "u1@x.io",
    ]


@pytest.mark.parametrize("allow,policy", [(True, "open"), (False, "closed")])
def test_allow_signup_becomes_the_policy(before, allow, policy):
    url, engine = before
    command.upgrade(_cfg(url), HF)
    _insert(
        engine, "platform_settings", key="allow_signup", value=allow, updated_at=WHEN
    )
    _insert(
        engine,
        "platform_settings",
        key="allowed_email_domains",
        value=["corp.example"],
        updated_at=WHEN,
    )
    command.upgrade(_cfg(url), POLICY)
    assert _setting(engine, "signup_policy") == policy
    assert _setting(engine, "allow_signup") is None
    assert _setting(engine, "allowed_email_domains") is None

    command.downgrade(_cfg(url), HF)
    assert _setting(engine, "allow_signup") is allow
    assert _setting(engine, "signup_policy") is None
