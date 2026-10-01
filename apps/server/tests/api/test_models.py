"""Tests for the /models API (providers, per-role defaults, test call)."""

from server.api.deps import get_credentials
from server.tests.creds import FULL, make_creds
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.core.config import config
from server.services.providers import CompletionResult, ProviderError

DEFAULTS = {
    "cleaning": "openai:gpt-4o-mini",
    "qa": "claude:claude-sonnet-5",
    "vision": "openai:vlm",
    "jobs": "claude:claude-sonnet-5",
}


def test_list_models(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
    # This user only has an OpenAI key.
    overrides = client.app.dependency_overrides  # ty: ignore[unresolved-attribute]
    overrides[get_credentials] = lambda: make_creds(
        openai_api_key="sk-user-0000000000000000", base_url_trusted=True
    )
    with patch("server.api.models.get_model_defaults", return_value=DEFAULTS):
        response = client.get("/models")

    assert response.status_code == 200
    body = response.json()
    assert body["defaults"] == DEFAULTS
    assert body["roles"] == ["cleaning", "qa", "vision", "jobs"]
    providers = {p["name"]: p for p in body["providers"]}
    assert providers["openai"]["configured"] is True
    assert [m["ref"] for m in providers["openai"]["models"]] == ["openai:gpt-4o-mini"]
    assert providers["claude"]["configured"] is False
    assert providers["claude"]["missing"] == [
        "your Claude token (`claude setup-token`) or Anthropic API key"
    ]
    assert "claude:claude-sonnet-5" in [m["ref"] for m in providers["claude"]["models"]]


def test_put_defaults(client: TestClient, owner):
    with (
        patch("server.api.models.update_model_defaults") as update,
        patch("server.api.models.get_model_defaults", return_value=DEFAULTS),
    ):
        response = client.put(
            "/models/defaults", json={"defaults": {"qa": "claude:claude-sonnet-5"}}
        )
    assert response.status_code == 200
    update.assert_called_once_with(owner.id, {"qa": "claude:claude-sonnet-5"}, FULL)
    assert response.json()["defaults"] == DEFAULTS


def test_put_defaults_rejects_bad_ref(client: TestClient):
    with patch(
        "server.api.models.update_model_defaults",
        side_effect=ValueError("Unknown model 'openai:nope'"),
    ):
        response = client.put("/models/defaults", json={"defaults": {"qa": "nope"}})
    assert response.status_code == 400
    assert "Unknown model" in response.json()["detail"]


def test_test_model_success(client: TestClient):
    with (
        patch("server.api.models.validate_ref", return_value="claude:claude-sonnet-5"),
        patch(
            "server.api.models.complete",
            new=AsyncMock(return_value=CompletionResult("Hi!", {"output_tokens": 2})),
        ),
    ):
        response = client.post("/models/test", json={"ref": "claude:claude-sonnet-5"})
    body = response.json()
    assert response.status_code == 200
    assert (body["ok"], body["text"], body["usage"]) == (
        True,
        "Hi!",
        {"output_tokens": 2},
    )
    assert body["latency_ms"] >= 0


def test_test_model_reports_provider_errors(client: TestClient):
    with (
        patch("server.api.models.validate_ref", return_value="claude:claude-sonnet-5"),
        patch(
            "server.api.models.complete",
            new=AsyncMock(side_effect=ProviderError("rate limited")),
        ),
    ):
        response = client.post("/models/test", json={"ref": "claude:claude-sonnet-5"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "rate limited"


def test_test_model_rejects_unknown_ref(client: TestClient):
    response = client.post("/models/test", json={"ref": "openai:does-not-exist"})
    assert response.status_code == 400
