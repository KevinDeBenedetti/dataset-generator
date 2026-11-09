"""Stored secrets: encrypted at rest, per user, write-only, never in reprs."""

from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.core.crypto import generate_key
from server.models.user import User
from server.models.user_secret import UserSecret
from server.services import user_secrets
from server.services.credentials import (
    CLAUDE_TOKEN,
    HF_TOKEN,
    OPENAI_API_KEY,
    Credentials,
    resolve_credentials,
)
from server.services.user_secrets import (
    SecretError,
    delete_secret,
    get_settings,
    load_credentials,
    rewrap_all,
    secret_statuses,
    set_secret,
    update_settings,
)

ALICE, BOB = "alice", "bob"
CANARY = "sk-canary-1234567890abcdef"


@pytest.fixture(autouse=True)
def store(monkeypatch, test_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(user_secrets, "get_scoped_db", scoped)
    monkeypatch.setattr(config, "secrets_encryption_keys_raw", f"k1:{generate_key()}")
    monkeypatch.setattr(config, "allow_env_credentials", False)
    with scoped() as db:
        db.add(User(id=ALICE, email="a@test.local", role="user"))
        db.add(User(id=BOB, email="b@test.local", role="user"))
        db.commit()
    return scoped


def test_the_database_never_holds_the_plaintext(store):
    set_secret(ALICE, OPENAI_API_KEY, CANARY)

    with store() as db:
        stored = db.execute(text("SELECT ciphertext, hint FROM user_secrets")).one()
    assert CANARY not in stored.ciphertext
    assert stored.hint == CANARY[-4:]
    assert load_credentials(ALICE).secret(OPENAI_API_KEY) == CANARY


def test_statuses_are_write_only(store):
    set_secret(ALICE, OPENAI_API_KEY, CANARY)
    set_secret(ALICE, CLAUDE_TOKEN, "sk-ant-oat01-" + "x" * 30)

    statuses = secret_statuses(ALICE)
    assert statuses[OPENAI_API_KEY]["configured"] is True
    assert statuses[OPENAI_API_KEY]["hint"] == CANARY[-4:]
    assert statuses[CLAUDE_TOKEN]["hint"] is None  # OAuth tokens get no hint
    assert statuses[HF_TOKEN]["configured"] is False
    assert CANARY not in repr(statuses)


def test_each_user_only_gets_their_own_secrets():
    set_secret(ALICE, OPENAI_API_KEY, CANARY)

    assert load_credentials(BOB).has(OPENAI_API_KEY) is False
    assert secret_statuses(BOB)[OPENAI_API_KEY]["configured"] is False


def test_a_row_moved_to_another_user_does_not_decrypt(store):
    set_secret(ALICE, OPENAI_API_KEY, CANARY)
    with store() as db:
        db.execute(text("UPDATE user_secrets SET user_id = :b"), {"b": BOB})
        db.commit()

    assert load_credentials(BOB).has(OPENAI_API_KEY) is False  # unreadable == unset


def test_replace_and_delete():
    set_secret(ALICE, HF_TOKEN, "hf_" + "a" * 30)
    set_secret(ALICE, HF_TOKEN, "hf_" + "b" * 30)
    assert load_credentials(ALICE).secret(HF_TOKEN).endswith("b" * 30)

    assert delete_secret(ALICE, HF_TOKEN) is True
    assert delete_secret(ALICE, HF_TOKEN) is False
    assert load_credentials(ALICE).has(HF_TOKEN) is False


@pytest.mark.parametrize("value", ["", "   ", "has a space", "x" * 5000])
def test_invalid_values_are_refused(value):
    with pytest.raises(SecretError):
        set_secret(ALICE, OPENAI_API_KEY, value)
    with pytest.raises(SecretError, match="Unknown"):
        set_secret(ALICE, "nope", "value")


def test_settings_merge_clear_and_are_per_user():
    update_settings(ALICE, {"hf_namespace": "alice-ns", "github_username": "al"})
    update_settings(ALICE, {"github_username": ""})

    assert get_settings(ALICE)["hf_namespace"] == "alice-ns"
    assert get_settings(ALICE)["github_username"] == ""
    assert get_settings(BOB)["hf_namespace"] == ""
    with pytest.raises(SecretError, match="Unknown"):
        update_settings(ALICE, {"database_url": "x"})


def test_credentials_never_print_their_values():
    set_secret(ALICE, OPENAI_API_KEY, CANARY)
    creds = load_credentials(ALICE)

    assert CANARY not in repr(creds)
    assert CANARY not in str(creds)
    assert CANARY not in repr(creds.openai_api_key)


def test_env_fallback_only_where_allowed(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-key-000000")
    monkeypatch.setenv("HF_TOKEN", "hf_server")

    monkeypatch.setattr(config, "allow_env_credentials", False)
    assert resolve_credentials(ALICE).has(OPENAI_API_KEY) is False

    monkeypatch.setattr(config, "allow_env_credentials", True)
    set_secret(ALICE, OPENAI_API_KEY, CANARY)
    creds = resolve_credentials(ALICE)
    assert creds.secret(OPENAI_API_KEY) == CANARY  # the user's own wins
    assert creds.secret(HF_TOKEN) == "hf_server"  # a missing one falls back
    assert Credentials.from_env().secret(OPENAI_API_KEY) == "sk-server-key-000000"


def _server_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-key-000000")
    monkeypatch.setenv(
        "OPENAI_BASE_URL", "http://litellm.litellm.svc.cluster.local:4000/v1"
    )
    monkeypatch.setattr(config, "allow_env_credentials", False)  # production


def _promote(store, user_id):
    with store() as db:
        db.get(User, user_id).role = "admin"
        db.commit()


def test_an_admin_without_a_key_uses_the_servers_endpoint(store, monkeypatch):
    _server_endpoint(monkeypatch)
    monkeypatch.setattr(config, "server_llm_for_admins", True)
    _promote(store, ALICE)

    lent = resolve_credentials(ALICE)
    assert lent.secret(OPENAI_API_KEY) == "sk-server-key-000000"
    assert lent.openai_base_url.startswith("http://litellm.litellm.svc")
    # The operator's own endpoint: an in-cluster http URL is fine.
    assert lent.base_url_trusted is True and lent.openai_from_server is True
    # Only that: the server's other keys stay its own.
    monkeypatch.setenv("HF_TOKEN", "hf_server")
    assert resolve_credentials(ALICE).has(HF_TOKEN) is False

    # Other users bring their own, whatever the request says about them.
    assert resolve_credentials(BOB).has(OPENAI_API_KEY) is False
    assert resolve_credentials(ALICE, is_admin=False).has(OPENAI_API_KEY) is False


def test_an_admins_own_key_wins_with_their_own_endpoint(store, monkeypatch):
    _server_endpoint(monkeypatch)
    monkeypatch.setattr(config, "server_llm_for_admins", True)
    _promote(store, ALICE)
    set_secret(ALICE, OPENAI_API_KEY, CANARY)

    creds = resolve_credentials(ALICE)
    assert creds.secret(OPENAI_API_KEY) == CANARY
    assert creds.openai_base_url == "" and creds.base_url_trusted is False
    assert creds.openai_from_server is False


def test_the_server_lends_nothing_unless_asked_to(store, monkeypatch):
    _server_endpoint(monkeypatch)
    monkeypatch.setattr(config, "server_llm_for_admins", False)
    _promote(store, ALICE)
    assert resolve_credentials(ALICE).has(OPENAI_API_KEY) is False


def test_rotation_rewraps_everything(store):
    set_secret(ALICE, OPENAI_API_KEY, CANARY)
    old = config.secrets_encryption_keys_raw
    config.secrets_encryption_keys_raw = f"k2:{generate_key()},{old}"

    with store() as db:
        counts = rewrap_all(db)
        assert counts == {"rewrapped": 1, "unchanged": 0, "failed": 0}
        assert db.query(UserSecret).one().key_id == "k2"
    assert load_credentials(ALICE).secret(OPENAI_API_KEY) == CANARY
