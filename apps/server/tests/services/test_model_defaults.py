"""Per-role default models: DB rows over env fallbacks."""

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.models.user import User
from server.tests.creds import FULL
from server.services import model_defaults
from server.services.model_defaults import (
    env_defaults,
    get_model_defaults,
    resolve_model,
    update_model_defaults,
)

USER = "user-1"
OTHER = "user-2"


@pytest.fixture(autouse=True)
def _env_models(monkeypatch):
    monkeypatch.setattr(config, "model_cleaning", "gpt-clean")
    monkeypatch.setattr(config, "model_qa", "gpt-qa")
    monkeypatch.setattr(config, "openai_vlm_model", "vlm")
    monkeypatch.setattr(config, "qa_job_model", "claude:claude-sonnet-5")
    monkeypatch.setattr(config, "available_models", ["gpt-clean", "gpt-qa", "vlm"])


@pytest.fixture
def db(monkeypatch, test_engine):
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(model_defaults, "get_scoped_db", scoped)

    # Defaults belong to a user: both test users must exist.
    with scoped() as session:
        session.add(User(id=USER, email="u1@test.local", role="user"))
        session.add(User(id=OTHER, email="u2@test.local", role="user"))
        session.commit()


def test_env_defaults_are_normalized():
    assert env_defaults() == {
        "cleaning": "openai:gpt-clean",
        "qa": "openai:gpt-qa",
        "vision": "openai:vlm",
        "jobs": "claude:claude-sonnet-5",
    }


def test_db_unreachable_falls_back_to_env(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("no db")
        yield  # pragma: no cover

    monkeypatch.setattr(model_defaults, "get_scoped_db", broken)
    assert get_model_defaults(USER) == env_defaults()


def test_stored_defaults_override_env(db):
    update_model_defaults(USER, {"qa": "claude:claude-sonnet-5"}, FULL)
    defaults = get_model_defaults(USER)
    assert defaults["qa"] == "claude:claude-sonnet-5"
    assert defaults["cleaning"] == "openai:gpt-clean"  # untouched role keeps env

    update_model_defaults(USER, {"qa": "gpt-qa"}, FULL)  # upsert, bare id normalized
    assert get_model_defaults(USER)["qa"] == "openai:gpt-qa"


def test_update_rejects_unknown_role_or_model(db):
    with pytest.raises(ValueError, match="Unknown role"):
        update_model_defaults(USER, {"nope": "openai:gpt-qa"}, FULL)
    with pytest.raises(ValueError, match="Unknown model"):
        update_model_defaults(USER, {"qa": "openai:missing"}, FULL)


def test_resolve_model_prefers_the_request(db):
    assert (
        resolve_model("qa", "claude:claude-opus-5-5", user_id=USER)
        == "claude:claude-opus-5-5"
    )
    assert resolve_model("qa", user_id=USER) == "openai:gpt-qa"


def test_each_user_has_their_own_defaults(db):
    update_model_defaults(USER, {"qa": "claude:claude-sonnet-5"}, FULL)

    assert get_model_defaults(USER)["qa"] == "claude:claude-sonnet-5"
    assert get_model_defaults(OTHER)["qa"] == "openai:gpt-qa"  # env fallback
    assert resolve_model("qa", user_id=OTHER) == "openai:gpt-qa"
    assert resolve_model("qa", user_id=USER) == "claude:claude-sonnet-5"
