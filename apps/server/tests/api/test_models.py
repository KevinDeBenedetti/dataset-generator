"""Tests for the /models API (the provider, your LLM, the test call)."""

from server.api.deps import get_credentials
from server.tests.creds import FULL, make_creds
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.core.config import config
from server.services.providers import CompletionResult, ProviderError


def test_list_models(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
    monkeypatch.setattr(config, "openai_embedding_model", "")
    # This user only has an OpenAI key.
    overrides = client.app.dependency_overrides  # ty: ignore[unresolved-attribute]
    overrides[get_credentials] = lambda: make_creds(
        openai_api_key="sk-user-0000000000000000", base_url_trusted=True
    )
    with patch(
        "server.api.models.get_default_model", return_value="openai:gpt-4o-mini"
    ):
        response = client.get("/models")

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "openai:gpt-4o-mini"
    assert body["embedding_model"] == ""  # none: the checks compare the text
    assert [p["name"] for p in body["providers"]] == ["openai"]
    (openai,) = body["providers"]
    assert openai["configured"] is True
    assert [m["ref"] for m in openai["models"]] == ["openai:gpt-4o-mini"]
    assert openai["endpoint"] == "api.openai.com"
    assert openai["lent"] is False


def test_list_models_shows_the_endpoint_and_the_embedding_model(
    client: TestClient, monkeypatch
):
    """An admin on the server's LiteLLM: where the calls go, that the key is
    the server's, and what the duplicate checks embed with."""
    monkeypatch.setattr(config, "available_models", ["chat-default"])
    monkeypatch.setattr(config, "openai_embedding_model", "embed-default")
    overrides = client.app.dependency_overrides  # ty: ignore[unresolved-attribute]
    overrides[get_credentials] = lambda: make_creds(
        openai_api_key="sk-server-0000000000000",
        openai_base_url="http://litellm.litellm.svc.cluster.local:4000/v1",
        base_url_trusted=True,
        openai_from_server=True,
    )
    with patch(
        "server.api.models.get_default_model", return_value="openai:chat-default"
    ):
        body = client.get("/models").json()

    (openai,) = body["providers"]
    assert openai["endpoint"] == "litellm.litellm.svc.cluster.local"
    assert openai["lent"] is True
    assert [m["ref"] for m in openai["models"]] == ["openai:chat-default"]
    assert [m["ref"] for m in openai["embedding_models"]] == ["openai:embed-default"]
    assert body["model"] == "openai:chat-default"
    assert body["embedding_model"] == "openai:embed-default"


def test_put_default(client: TestClient, owner):
    with (
        patch("server.api.models.set_default_model") as update,
        patch("server.api.models.get_default_model", return_value="openai:gpt-4o"),
    ):
        response = client.put("/models/default", json={"model": "openai:gpt-4o"})
    assert response.status_code == 200
    update.assert_called_once_with(owner.id, "openai:gpt-4o", FULL)
    assert response.json()["model"] == "openai:gpt-4o"


def test_put_default_rejects_bad_ref(client: TestClient):
    with patch(
        "server.api.models.set_default_model",
        side_effect=ValueError("Unknown model 'openai:nope'"),
    ):
        response = client.put("/models/default", json={"model": "nope"})
    assert response.status_code == 400
    assert "Unknown model" in response.json()["detail"]


def test_the_per_step_defaults_route_is_gone(client: TestClient):
    response = client.put("/models/defaults", json={"defaults": {"qa": "x"}})
    assert response.status_code in (404, 405)


def test_test_model_success(client: TestClient):
    with (
        patch("server.api.models.validate_ref", return_value="openai:gpt-4o-mini"),
        patch(
            "server.api.models.complete",
            new=AsyncMock(return_value=CompletionResult("Hi!", {"output_tokens": 2})),
        ),
    ):
        response = client.post("/models/test", json={"ref": "openai:gpt-4o-mini"})
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
        patch("server.api.models.validate_ref", return_value="openai:gpt-4o-mini"),
        patch(
            "server.api.models.complete",
            new=AsyncMock(side_effect=ProviderError("rate limited")),
        ),
    ):
        response = client.post("/models/test", json={"ref": "openai:gpt-4o-mini"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "rate limited"


def test_test_model_rejects_unknown_ref(client: TestClient):
    response = client.post("/models/test", json={"ref": "openai:does-not-exist"})
    assert response.status_code == 400
