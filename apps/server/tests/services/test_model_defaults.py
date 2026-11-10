"""Each user's LLM: a saved row over OPENAI_LLM_MODEL."""

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.models.model_defaults import ModelDefault
from server.models.user import User
from server.tests.creds import FULL
from server.services import model_defaults
from server.services.model_defaults import (
    LLM_ROLE,
    env_default,
    get_default_model,
    resolve_model,
    set_default_model,
)

USER = "user-1"
OTHER = "user-2"


@pytest.fixture(autouse=True)
def _env_models(monkeypatch):
    monkeypatch.setattr(config, "openai_llm_model", "gpt-env")
    monkeypatch.setattr(config, "available_models", ["gpt-env", "gpt-mine"])


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

    # A saved model belongs to a user: both test users must exist.
    with scoped() as session:
        session.add(User(id=USER, email="u1@test.local", role="user"))
        session.add(User(id=OTHER, email="u2@test.local", role="user"))
        session.commit()


def test_the_env_default_is_normalized(monkeypatch):
    assert env_default() == "openai:gpt-env"
    monkeypatch.setattr(config, "openai_llm_model", "")
    assert env_default() == ""


def test_db_unreachable_falls_back_to_env(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("no db")
        yield  # pragma: no cover

    monkeypatch.setattr(model_defaults, "get_scoped_db", broken)
    assert get_default_model(USER) == "openai:gpt-env"


def test_a_saved_model_overrides_env_and_is_upserted(db):
    assert set_default_model(USER, "openai:gpt-mine", FULL) == "openai:gpt-mine"
    assert get_default_model(USER) == "openai:gpt-mine"

    set_default_model(USER, "gpt-env", FULL)  # upsert, bare id normalized
    assert get_default_model(USER) == "openai:gpt-env"
    with model_defaults.get_scoped_db() as session:
        rows = session.query(ModelDefault).filter(ModelDefault.user_id == USER).all()
    assert [(r.role, r.model_ref) for r in rows] == [(LLM_ROLE, "openai:gpt-env")]


def test_an_unknown_model_is_refused(db):
    with pytest.raises(ValueError, match="Unknown model"):
        set_default_model(USER, "openai:missing", FULL)


def test_resolve_model_prefers_the_request(db):
    assert resolve_model("openai:other", user_id=USER) == "openai:other"
    assert resolve_model(user_id=USER) == "openai:gpt-env"
    assert resolve_model() == "openai:gpt-env"


def test_each_user_has_their_own_model(db):
    set_default_model(USER, "openai:gpt-mine", FULL)

    assert resolve_model(user_id=USER) == "openai:gpt-mine"
    assert resolve_model(user_id=OTHER) == "openai:gpt-env"  # env fallback
