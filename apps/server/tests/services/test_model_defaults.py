"""Per-role default models: DB rows over env fallbacks."""

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.services import model_defaults
from server.services.model_defaults import (
    env_defaults,
    get_model_defaults,
    resolve_model,
    update_model_defaults,
)


@pytest.fixture(autouse=True)
def _env_models(monkeypatch):
    monkeypatch.setattr(config, "model_cleaning", "gpt-clean")
    monkeypatch.setattr(config, "model_qa", "gpt-qa")
    monkeypatch.setattr(config, "openai_vlm_model", "vlm")
    monkeypatch.setattr(config, "qa_job_model", "claude:claude-sonnet-5")
    monkeypatch.setattr(config, "openai_api_key", "k")
    monkeypatch.setattr(config, "available_models", ["gpt-clean", "gpt-qa", "vlm"])
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")


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
    assert get_model_defaults() == env_defaults()


def test_stored_defaults_override_env(db):
    update_model_defaults({"qa": "claude:claude-sonnet-5"})
    defaults = get_model_defaults()
    assert defaults["qa"] == "claude:claude-sonnet-5"
    assert defaults["cleaning"] == "openai:gpt-clean"  # untouched role keeps env

    update_model_defaults({"qa": "gpt-qa"})  # upsert, bare id normalized
    assert get_model_defaults()["qa"] == "openai:gpt-qa"


def test_update_rejects_unknown_role_or_model(db):
    with pytest.raises(ValueError, match="Unknown role"):
        update_model_defaults({"nope": "openai:gpt-qa"})
    with pytest.raises(ValueError, match="Unknown model"):
        update_model_defaults({"qa": "openai:missing"})


def test_resolve_model_prefers_the_request(db):
    assert resolve_model("qa", "claude:claude-opus-5-5") == "claude:claude-opus-5-5"
    assert resolve_model("qa") == "openai:gpt-qa"
