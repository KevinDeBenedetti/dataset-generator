"""Live key checks: what each provider's answer means, and that nothing leaks."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.services import secret_validation as sv
from server.services.secret_validation import check_secret
from server.tests.creds import make_creds

KEY = "sk-canary-0123456789abcdef"


class _Client:
    """An ``httpx.AsyncClient`` stand-in answering one GET."""

    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.seen: tuple = ()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, headers=None):
        self.seen = (url, headers)
        if self.error:
            raise self.error
        return self.response


def _patch_http(client):
    return patch.object(sv.httpx, "AsyncClient", lambda **kw: client)


async def test_github_token_ok_and_rejected():
    ok = _Client(httpx.Response(200, json={}))
    with _patch_http(ok):
        result = await check_secret("github_token", "ghp_x" * 5, make_creds())
    assert result.ok and ok.seen[0] == "https://api.github.com/user"
    assert ok.seen[1]["Authorization"] == "Bearer " + "ghp_x" * 5

    with _patch_http(_Client(httpx.Response(401))):
        assert (await check_secret("github_token", "bad", make_creds())).ok is False
    with _patch_http(_Client(error=httpx.ConnectError("down"))):
        result = await check_secret("github_token", "bad", make_creds())
    assert not result.ok and "Could not reach" in result.message


async def test_anthropic_key_sends_only_its_own_key():
    client = _Client(httpx.Response(200, json={}))
    with _patch_http(client):
        assert (
            await check_secret("anthropic_api_key", "sk-ant-key-1", make_creds())
        ).ok
    assert client.seen[1]["x-api-key"] == "sk-ant-key-1"


@pytest.mark.parametrize(
    "who, namespace, ok",
    [
        ({"name": "alice", "auth": {"accessToken": {"role": "write"}}}, "", True),
        ({"name": "alice", "auth": {"accessToken": {"role": "read"}}}, "", False),
        ({"name": "alice", "auth": {"accessToken": {"role": "write"}}}, "alice", True),
        (
            {
                "name": "alice",
                "orgs": [{"name": "acme"}],
                "auth": {"accessToken": {"role": "fineGrained"}},
            },
            "acme",
            True,
        ),
        (
            {"name": "alice", "auth": {"accessToken": {"role": "write"}}},
            "someone-else",
            False,
        ),
    ],
)
async def test_hugging_face_token_needs_write_and_the_declared_namespace(
    who, namespace, ok
):
    with patch.object(sv, "_hf_whoami", return_value=who):
        result = await check_secret(
            "hf_token", "hf_x" * 8, make_creds(hf_namespace=namespace)
        )
    assert result.ok is ok


async def test_hugging_face_rejection_does_not_echo_the_provider_error():
    with patch.object(sv, "_hf_whoami", side_effect=RuntimeError(f"401 for {KEY}")):
        result = await check_secret("hf_token", KEY, make_creds())
    assert not result.ok and KEY not in result.message


async def test_openai_check_uses_the_candidate_key_and_a_guarded_client():
    seen = {}

    def build(self, creds):
        seen["key"] = creds.secret("openai_api_key")
        seen["trusted"] = creds.base_url_trusted
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.models.list = AsyncMock(return_value=MagicMock(data=[]))
        return client

    with patch.object(sv.OpenAIProvider, "build_client", build):
        result = await check_secret("openai_api_key", KEY, make_creds())
    assert result.ok
    assert seen == {"key": KEY, "trusted": False}


async def test_openai_auth_failure_and_bad_endpoint_are_reported():
    class Unauthorized(Exception):
        status_code = 401

    def build(self, creds):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.models.list = AsyncMock(side_effect=Unauthorized(f"bad {KEY}"))
        return client

    with patch.object(sv.OpenAIProvider, "build_client", build):
        result = await check_secret("openai_api_key", KEY, make_creds())
    assert result.message == "OpenAI rejected this key"

    creds = make_creds(openai_base_url="https://169.254.169.254/v1")
    result = await check_secret("openai_api_key", KEY, creds)
    assert not result.ok and "not an allowed endpoint" in result.message


async def test_claude_token_is_only_shape_checked():
    good = await check_secret("claude_token", "sk-ant-oat01-" + "a" * 30, make_creds())
    assert good.ok and good.checked is False
    bad = await check_secret("claude_token", "nope", make_creds())
    assert not bad.ok and bad.checked is True
