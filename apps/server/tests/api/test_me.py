"""The user's own keys: saved encrypted, validated live, write-only, never leaked."""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from server.core.config import config
from server.services.secret_validation import Check
from server.services.users import create_user

CANARY = "sk-canary-0123456789abcdefABCDEF"
HF_CANARY = "hf_CanaryToken0123456789abcdefghij"


@pytest.fixture
def alice(test_db):
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def bob(test_db):
    return create_user(test_db, email="bob@test.local", password="pw12345")


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    # Production-like: no env fallback, so what a user sees is only their own.
    monkeypatch.setattr(config, "allow_env_credentials", False)
    monkeypatch.setattr(config, "enable_claude_provider", True)


@pytest.fixture
def ok_check():
    with patch(
        "server.api.me.check_secret",
        new=AsyncMock(return_value=Check(True, True, "The key works")),
    ) as check:
        yield check


def _put(client, kind, value, **extra):
    return client.put(f"/me/secrets/{kind}", json={"value": value, **extra})


def test_saving_a_key_returns_status_only(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)

    response = _put(client, "openai_api_key", CANARY)

    assert response.status_code == 200
    body = response.json()
    assert body["secret"] == {
        "kind": "openai_api_key",
        "configured": True,
        "hint": CANARY[-4:],
        "updated_at": body["secret"]["updated_at"],
    }
    assert CANARY not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_no_route_ever_returns_a_secret(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)
    _put(client, "openai_api_key", CANARY)
    _put(client, "hf_token", HF_CANARY)

    for path in ("/me/secrets", "/me/settings", "/models", "/jobs"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert CANARY not in response.text and HF_CANARY not in response.text, path
        assert response.headers.get("cache-control") == "no-store" or path in (
            "/models",
            "/jobs",
        )

    listed = client.get("/me/secrets").json()["secrets"]
    by_kind = {s["kind"]: s for s in listed}
    assert by_kind["openai_api_key"]["configured"] is True
    assert by_kind["claude_token"]["configured"] is False


def test_the_secret_is_encrypted_in_the_database(alice, client_for, ok_check, test_db):
    _put(client_for(alice, real_credentials=True), "openai_api_key", CANARY)

    stored = test_db.execute(text("SELECT ciphertext FROM user_secrets")).scalar_one()
    assert CANARY not in stored


def test_a_failed_live_check_refuses_the_key_unless_forced(alice, client_for):
    client = client_for(alice, real_credentials=True)
    bad = Check(False, True, "OpenAI rejected this key")
    with patch("server.api.me.check_secret", new=AsyncMock(return_value=bad)):
        refused = _put(client, "openai_api_key", CANARY)
        assert refused.status_code == 422
        assert refused.json()["detail"] == "OpenAI rejected this key"
        assert CANARY not in refused.text
        assert client.get("/me/secrets").json()["secrets"][0]["configured"] is False

        forced = _put(client, "openai_api_key", CANARY, force=True)
        assert forced.status_code == 200
        assert forced.json()["check"]["ok"] is False


def test_a_token_that_can_only_be_format_checked_is_saved(alice, client_for):
    client = client_for(alice, real_credentials=True)
    response = _put(client, "claude_token", "sk-ant-oat01-" + "a" * 40)
    assert response.status_code == 200
    assert response.json()["check"]["checked"] is False
    assert response.json()["secret"]["hint"] is None  # OAuth tokens get no hint

    # A wrongly-shaped one is refused like any failed check.
    wrong = _put(client, "claude_token", "not-a-claude-token")
    assert wrong.status_code == 422
    assert "setup-token" in wrong.json()["detail"]


def test_unknown_kinds_and_bad_values(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)
    assert _put(client, "database_url", "x" * 20).status_code == 404
    assert client.delete("/me/secrets/nope").status_code == 404
    assert _put(client, "openai_api_key", "has a space").status_code == 422
    assert (
        client.put("/me/secrets/openai_api_key", json={"value": ""}).status_code == 422
    )


def test_delete_forgets_the_key(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)
    _put(client, "hf_token", HF_CANARY)

    assert client.delete("/me/secrets/hf_token").status_code == 204

    by_kind = {s["kind"]: s for s in client.get("/me/secrets").json()["secrets"]}
    assert by_kind["hf_token"]["configured"] is False


def test_users_never_see_each_others_keys(alice, bob, client_for, ok_check):
    a = client_for(alice, real_credentials=True)
    b = client_for(bob, real_credentials=True)
    _put(a, "openai_api_key", CANARY)

    assert {s["kind"]: s for s in b.get("/me/secrets").json()["secrets"]}[
        "openai_api_key"
    ]["configured"] is False

    # And the app agrees: Bob has no usable OpenAI provider, Alice does.
    def openai_configured(client):
        providers = {p["name"]: p for p in client.get("/models").json()["providers"]}
        return providers["openai"]["configured"]

    assert openai_configured(a) is True
    assert openai_configured(b) is False


def test_a_users_call_is_made_with_their_own_key(alice, bob, client_for, ok_check):
    """Two users hit the same endpoint; the model call carries each one's key."""
    a = client_for(alice, real_credentials=True)
    b = client_for(bob, real_credentials=True)
    _put(a, "openai_api_key", "sk-alice-000000000000000")
    _put(b, "openai_api_key", "sk-bob-00000000000000000")
    used = []

    async def fake_complete(ref, req, creds):
        from server.services.providers import CompletionResult

        used.append(creds.secret("openai_api_key"))
        return CompletionResult("pong")

    with patch("server.api.models.complete", new=fake_complete):
        for client in (a, b, a, b):
            response = client.post(
                "/models/test", json={"ref": "openai:gpt-4o-mini", "prompt": "ping"}
            )
            assert response.status_code == 200, response.text

    assert used == [
        "sk-alice-000000000000000",
        "sk-bob-00000000000000000",
        "sk-alice-000000000000000",
        "sk-bob-00000000000000000",
    ]


def test_settings_roundtrip_and_vetting(alice, client_for):
    client = client_for(alice, real_credentials=True)

    saved = client.put(
        "/me/settings",
        json={"settings": {"hf_namespace": "alice-ns", "github_username": "alice"}},
    )
    assert saved.status_code == 200
    assert client.get("/me/settings").json()["settings"]["hf_namespace"] == "alice-ns"

    # A base URL must be https and an allowed endpoint.
    for url in ("http://api.openai.com/v1", "https://evil.example.com/v1"):
        bad = client.put("/me/settings", json={"settings": {"openai_base_url": url}})
        assert bad.status_code == 422, url
    good = client.put(
        "/me/settings",
        json={"settings": {"openai_base_url": "https://api.openai.com/v1"}},
    )
    assert good.status_code == 200
    assert (
        client.put("/me/settings", json={"settings": {"secret_key": "x"}}).status_code
        == 422
    )


def test_test_endpoint_rechecks_a_saved_key(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)
    assert client.post("/me/secrets/openai_api_key/test").status_code == 404
    _put(client, "openai_api_key", CANARY)

    response = client.post("/me/secrets/openai_api_key/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert CANARY not in response.text


def test_saving_and_testing_keys_is_throttled(alice, client_for, ok_check):
    client = client_for(alice, real_credentials=True)
    codes = [_put(client, "openai_api_key", CANARY).status_code for _ in range(40)]
    assert 429 in codes
    assert codes[0] == 200


def test_secrets_never_reach_the_logs(alice, client_for, caplog):
    client = client_for(alice, real_credentials=True)
    boom = AsyncMock(side_effect=RuntimeError(f"upstream said: bad key {CANARY}"))
    with caplog.at_level(logging.DEBUG), patch("server.api.me.check_secret", new=boom):
        try:
            _put(client, "openai_api_key", CANARY)
        except RuntimeError:
            pass
    assert CANARY not in caplog.text


def test_identities_list_and_unlink_rules(alice, bob, client_for, test_db):
    from server.models.identity import Identity

    test_db.add_all(
        [
            Identity(id="gh-a", user_id=alice.id, provider="github", subject="1"),
            Identity(id="ik-a", user_id=alice.id, provider="infomaniak", subject="2"),
            Identity(id="gh-b", user_id=bob.id, provider="github", subject="3"),
        ]
    )
    test_db.commit()
    a = client_for(alice, real_credentials=True)

    body = a.get("/me/identities").json()
    assert sorted(i["provider"] for i in body["identities"]) == ["github", "infomaniak"]
    assert body["has_password"] is True and body["locked_admin"] is False

    assert a.delete("/me/identities/gh-b").status_code == 404  # Bob's
    assert a.delete("/me/identities/gh-a").status_code == 204
    assert test_db.get(Identity, "gh-b") is not None


def test_a_deployed_server_offers_no_claude_at_all(
    alice, client_for, monkeypatch, ok_check
):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(config, "environment", "production")
    client = client_for(alice, real_credentials=True)

    kinds = {s["kind"] for s in client.get("/me/secrets").json()["secrets"]}
    assert "claude_token" not in kinds and "anthropic_api_key" not in kinds
    assert _put(client, "claude_token", "sk-ant-oat01-" + "a" * 30).status_code == 404
    providers = [p["name"] for p in client.get("/models").json()["providers"]]
    assert providers == ["openai"]
    # A claude: default saved during development falls back to the qa model.
    assert not any(
        v.startswith("claude:")
        for v in client.get("/models").json()["defaults"].values()
    )
