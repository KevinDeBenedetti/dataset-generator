"""Model providers: reference parsing, validation, and both providers' calls
(OpenAI client and Claude Agent SDK mocked — no network, no Claude Code)."""

import asyncio
import base64
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from server.core import net
from server.core.config import config
from server.tests.creds import FULL, NONE, make_creds
from server.services.providers import (
    CompletionRequest,
    ProviderError,
    complete,
    normalize_ref,
    parse_ref,
    validate_ref,
)
from server.services.providers import registry
from server.core.net import PinnedTransport
from server.services.providers import claude as claude_module
from server.services.providers import openai as openai_module
from server.services.providers.claude import ClaudeProvider
from server.services.providers.openai import (
    OpenAIProvider,
    check_base_url,
    classify_model_id,
)


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("claude:claude-sonnet-5-5", ("claude", "claude-sonnet-5-5")),
        ("openai:gpt-4o", ("openai", "gpt-4o")),
        ("gpt-4o", ("openai", "gpt-4o")),
        # A colon inside an OpenAI-compatible id isn't a provider prefix.
        ("llama3:8b", ("openai", "llama3:8b")),
        ("openai:llama3:8b", ("openai", "llama3:8b")),
    ],
)
def test_parse_ref(ref, expected):
    assert parse_ref(ref) == expected


def test_normalize_ref():
    assert normalize_ref("gpt-4o") == "openai:gpt-4o"


class TestValidateRef:
    def test_known_openai_model(self, monkeypatch):
        monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
        assert validate_ref("gpt-4o-mini", FULL) == "openai:gpt-4o-mini"

    def test_unknown_model(self, monkeypatch):
        monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
        with pytest.raises(ValueError, match="Unknown model 'openai:nope'"):
            validate_ref("openai:nope", FULL)

    def test_unconfigured_provider_says_what_to_add(self):
        with pytest.raises(ValueError, match="Claude token.*Settings"):
            validate_ref("claude:claude-sonnet-5-5", NONE)
        with pytest.raises(ValueError, match=r"API key \(and endpoint\).*Settings"):
            validate_ref("openai:gpt-4o-mini", NONE)

    def test_claude_is_refused_outside_development_and_ci(self, monkeypatch):
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setattr(config, "environment", "production")
        with pytest.raises(ValueError, match="development and CI"):
            validate_ref("claude:claude-sonnet-5-5", FULL)

    def test_claude_models_override(self, monkeypatch):
        monkeypatch.setattr(config, "claude_models_raw", "claude-x, claude-y")
        assert validate_ref("claude:claude-y", FULL) == "claude:claude-y"
        with pytest.raises(ValueError):
            validate_ref("claude:claude-sonnet-5-5", FULL)

    def test_empty_model(self):
        with pytest.raises(ValueError, match="no model id"):
            validate_ref("claude:", FULL)

    def test_a_retired_claude_model_means_its_successor(self):
        # Saved before the catalogue moved on: still valid, as the successor.
        assert (
            validate_ref("claude:claude-sonnet-5", FULL) == "claude:claude-sonnet-5-5"
        )
        assert (
            validate_ref("claude:claude-haiku-4-5-20251001", FULL)
            == "claude:claude-haiku-5-5"
        )
        assert normalize_ref("claude:claude-sonnet-5") == "claude:claude-sonnet-5-5"


# --- OpenAI -------------------------------------------------------------------


def _openai_provider(monkeypatch, text="Hello"):
    provider = OpenAIProvider()
    client = MagicMock()
    usage = MagicMock()
    usage.model_dump.return_value = {"total_tokens": 7}
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"  {text} "))],
            usage=usage,
        )
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    built = []

    def build(creds):
        built.append(creds)
        return client

    monkeypatch.setattr(provider, "build_client", build)
    return provider, client, built


async def test_openai_text_completion(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    result = await provider.complete(
        "gpt-x", CompletionRequest(user="Hi", system="Sys"), FULL
    )
    assert result.text == "Hello" and result.usage == {"total_tokens": 7}
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-x"
    assert kwargs["messages"] == [
        {"role": "system", "content": "Sys"},
        {"role": "user", "content": "Hi"},
    ]
    assert "reasoning_effort" not in kwargs
    # The classic shape, which every OpenAI-compatible endpoint takes.
    assert kwargs["max_tokens"] == 4000 and kwargs["temperature"] == config.temperature
    assert "max_completion_tokens" not in kwargs


async def test_openai_image_payload(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    await provider.complete(
        "vlm",
        CompletionRequest(user="Transcribe", images=[(b"img", "image/png")]),
        FULL,
    )
    content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert (
        content[0]["image_url"]["url"]
        == "data:image/png;base64," + base64.b64encode(b"img").decode()
    )
    assert content[-1] == {"type": "text", "text": "Transcribe"}


@pytest.mark.parametrize("effort, sent", [("low", True), ("", False)])
async def test_openai_reasoning_effort(monkeypatch, effort, sent):
    """With an effort, the request takes the reasoning models' shape: the
    budget as max_completion_tokens and no temperature (the o-series and gpt-5
    refuse max_tokens and any temperature but theirs). Off, the classic one."""
    provider, client, _ = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "openai_reasoning_effort", effort)
    await provider.complete(
        "m", CompletionRequest(user="u", reasoning=True, max_tokens=1234), FULL
    )
    kwargs = client.chat.completions.create.call_args.kwargs
    assert ("reasoning_effort" in kwargs) is sent
    assert ("max_completion_tokens" in kwargs) is sent
    assert ("max_tokens" in kwargs) is not sent
    assert ("temperature" in kwargs) is not sent
    assert kwargs.get("max_completion_tokens", kwargs.get("max_tokens")) == 1234


async def test_openai_unconfigured():
    with pytest.raises(ProviderError, match="API key"):
        await OpenAIProvider().complete("m", CompletionRequest(user="u"), NONE)


async def test_each_call_uses_the_callers_own_credentials(monkeypatch):
    """One provider instance, two users: every call is built from its own creds."""
    provider, _client, built = _openai_provider(monkeypatch)
    alice = make_creds(openai_api_key="sk-alice-000000000000")
    bob = make_creds(openai_api_key="sk-bob-00000000000000")

    await provider.complete("m", CompletionRequest(user="u"), alice)
    await provider.complete("m", CompletionRequest(user="u"), bob)
    await asyncio.gather(
        provider.complete("m", CompletionRequest(user="u"), alice),
        provider.complete("m", CompletionRequest(user="u"), bob),
    )

    assert [c.secret("openai_api_key") for c in built] == [
        "sk-alice-000000000000",
        "sk-bob-00000000000000",
        "sk-alice-000000000000",
        "sk-bob-00000000000000",
    ]


async def test_the_real_client_carries_the_callers_key_and_is_pinned():
    """Un-mocked: the authorization the SDK client sends is the caller's own."""
    provider = OpenAIProvider()
    creds = make_creds(openai_api_key="sk-alice-000000000000")

    client = provider.build_client(creds)

    assert client.api_key == "sk-alice-000000000000"
    transport = client._client._transport
    assert isinstance(transport, PinnedTransport)  # a user's endpoint is guarded
    await client.close()


async def test_a_trusted_operator_endpoint_is_not_pinned():
    creds = make_creds(
        openai_api_key="sk-x-0000000000000000",
        openai_base_url="http://localhost:8080/v1",
        base_url_trusted=True,
    )
    client = OpenAIProvider().build_client(creds)
    assert not isinstance(client._client._transport, PinnedTransport)
    await client.close()


@pytest.mark.parametrize(
    "url, message",
    [
        ("http://api.openai.com/v1", "https"),
        ("https://evil.example.com/v1", "not an allowed endpoint"),
        ("https://user:pw@api.openai.com/v1", "credentials"),
    ],
)
def test_user_base_urls_are_vetted(url, message):
    with pytest.raises(ValueError, match=message):
        check_base_url(url)


def test_custom_base_url_needs_the_platform_flag(monkeypatch):
    with pytest.raises(ValueError):
        check_base_url("https://gateway.example.com/v1")
    monkeypatch.setattr(config, "allow_custom_base_url", True)
    assert check_base_url("https://gateway.example.com/v1")


async def test_a_disallowed_base_url_never_builds_a_client():
    creds = make_creds(
        openai_api_key="sk-x-0000000000000000",
        openai_base_url="https://169.254.169.254/v1",
    )
    with pytest.raises(ValueError):
        OpenAIProvider().build_client(creds)


async def test_openai_discovery_is_best_effort_and_per_key(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "available_models", ["configured"])
    client.models.list = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id="live")])
    )
    assert [m.id for m in await provider.list_models(FULL)] == ["configured", "live"]
    assert provider.knows("live", FULL)
    # Another user's account never sees (or validates against) that discovery.
    other = make_creds(openai_api_key="sk-other-00000000000000")
    assert not provider.knows("live", other)

    provider._discovered.clear()
    client.models.list = AsyncMock(side_effect=RuntimeError("down"))
    assert [m.id for m in await provider.list_models(FULL)] == ["configured"]


def _listing(*ids):
    return AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id=i) for i in ids])
    )


async def test_discovery_sorts_chat_from_embedding_models(monkeypatch):
    """A gateway lists every alias: only chat models are offered for the model
    roles, the embedding ones go to the collections, the rest nowhere."""
    provider, client, _ = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "available_models", [])
    client.models.list = _listing(
        "chat-default", "embed-default", "text-embedding-3-small", "moderation", "gpt-x"
    )
    client.get = AsyncMock(side_effect=RuntimeError("404"))  # not a LiteLLM

    await provider.discover(FULL)

    assert [m.id for m in provider.models(FULL)] == ["chat-default", "gpt-x"]
    assert [m.ref for m in provider.embedding_models(FULL)] == [
        "openai:embed-default",
        "openai:text-embedding-3-small",
    ]
    assert not provider.knows("embed-default", FULL)  # not a chat default


async def test_discovery_follows_litellm_model_modes(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "available_models", [])
    client.models.list = _listing("chat-free", "vectors", "guard")
    client.get = AsyncMock(
        return_value={
            "data": [
                # One entry per deployment: the first mode given wins.
                {"model_name": "chat-free", "model_info": {"mode": "chat"}},
                {"model_name": "chat-free", "model_info": {"mode": None}},
                {"model_name": "vectors", "model_info": {"mode": "embedding"}},
                {"model_name": "guard", "model_info": {"mode": "moderation"}},
            ]
        }
    )

    await provider.discover(FULL)

    assert client.get.call_args.args == ("/model/info",)
    assert [m.id for m in provider.models(FULL)] == ["chat-free"]
    assert [m.id for m in provider.embedding_models(FULL)] == ["vectors"]


async def test_the_configured_embedding_model_is_never_a_chat_model(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "available_models", ["chat-default"])
    monkeypatch.setattr(config, "openai_embedding_model", "my-vectors")
    client.models.list = _listing("chat-default", "my-vectors")  # an id with no hint
    client.get = AsyncMock(return_value={})

    await provider.discover(FULL)

    assert [m.id for m in provider.models(FULL)] == ["chat-default"]
    assert [m.id for m in provider.embedding_models(FULL)] == ["my-vectors"]
    # Without a key there is no endpoint to embed on.
    assert provider.embedding_models(NONE) == []


async def test_a_failed_discovery_is_not_retried_on_every_page_load(monkeypatch):
    provider, client, _ = _openai_provider(monkeypatch)
    client.models.list = AsyncMock(side_effect=RuntimeError("down"))
    await provider.discover(FULL)
    await provider.discover(FULL)
    assert client.models.list.call_count == 1


@pytest.mark.parametrize(
    "model_id, kind",
    [
        ("embed-default", "embedding"),
        ("text-embedding-3-large", "embedding"),
        ("nomic-embed-text", "embedding"),
        ("BAAI/bge-m3", "embedding"),
        ("omni-moderation-latest", "other"),
        ("whisper-1", "other"),
        ("chat-smart", "chat"),
        ("llama3:8b", "chat"),
    ],
)
def test_classify_model_id(model_id, kind):
    assert classify_model_id(model_id) == kind


def _embedding_client(monkeypatch, provider, dims=3):
    """A sync client whose embeddings.create answers in shuffled order."""
    client = MagicMock()
    sent = []

    def create(model, input, encoding_format):
        sent.append(list(input))
        data = [
            SimpleNamespace(index=i, embedding=[float(len(t))] * dims)
            for i, t in enumerate(input)
        ]
        return SimpleNamespace(data=list(reversed(data)))

    client.embeddings.create = MagicMock(side_effect=create)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(provider, "build_sync_client", lambda creds: client)
    return client, sent


def test_embed_batches_keep_the_order_and_never_send_an_empty_text(monkeypatch):
    provider = OpenAIProvider()
    client, sent = _embedding_client(monkeypatch, provider)
    monkeypatch.setattr(openai_module, "EMBED_BATCH", 2)

    vectors = provider.embed("embed-default", ["abc", "", "abcdef"], FULL)

    assert sent == [["abc", " "], ["abcdef"]]
    assert vectors == [[3.0] * 3, [1.0] * 3, [6.0] * 3]
    assert client.embeddings.create.call_args.kwargs["encoding_format"] == "float"


def test_embed_cuts_long_texts_and_bounds_a_request_by_size(monkeypatch):
    provider = OpenAIProvider()
    _, sent = _embedding_client(monkeypatch, provider)
    monkeypatch.setattr(openai_module, "EMBED_BATCH_CHARS", 10)

    provider.embed("m", ["x" * 9000, "abcdef", "abcdef"], FULL)

    assert [len(t) for t in sent[0]] == [openai_module.EMBED_MAX_CHARS]
    assert sent[1:] == [["abcdef"], ["abcdef"]]


def test_embed_failures_are_provider_errors(monkeypatch):
    provider = OpenAIProvider()
    client, _ = _embedding_client(monkeypatch, provider)
    client.embeddings.create.side_effect = RuntimeError("Error code: 404 - no model")
    with pytest.raises(ProviderError, match="openai:m embedding failed.*404"):
        provider.embed("m", ["a"], FULL)
    with pytest.raises(ProviderError, match="not configured"):
        provider.embed("m", ["a"], NONE)


def test_the_embedding_client_is_pinned_for_a_users_endpoint(monkeypatch):
    """Embeddings run in threads, on a sync client: a user's endpoint gets the
    same guard as the async one, the operator's none."""
    pinned = []

    def fake_pinned(**kwargs):
        pinned.append(kwargs)
        # No TLS context to build, no proxy from the env: nothing is sent.
        return httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            trust_env=False,
        )

    monkeypatch.setattr(net, "pinned_sync_client", fake_pinned)
    provider = OpenAIProvider()
    user = make_creds(openai_api_key="sk-alice-000000000000")
    provider.build_sync_client(user).close()
    assert pinned and pinned[0]["allowed_hosts"] == ["api.openai.com"]

    pinned.clear()
    operator = make_creds(
        openai_api_key="sk-x-0000000000000000",
        openai_base_url="http://litellm.litellm.svc.cluster.local:4000/v1",
        base_url_trusted=True,
    )
    provider.build_sync_client(operator).close()
    assert pinned == []


def test_the_endpoint_is_shown_and_a_lent_key_says_so():
    provider = OpenAIProvider()
    lent = make_creds(
        openai_api_key="sk-x-0000000000000000",
        openai_base_url="http://litellm.litellm.svc.cluster.local:4000/v1",
        base_url_trusted=True,
        openai_from_server=True,
    )
    assert provider.endpoint(lent) == "litellm.litellm.svc.cluster.local"
    assert provider.lent(lent) is True
    assert provider.endpoint(FULL) == "api.openai.com"
    assert provider.lent(FULL) is False


# --- Claude -------------------------------------------------------------------


class _ResultMessage:
    def __init__(self, **kw):
        self.subtype = kw.get("subtype", "success")
        self.is_error = kw.get("is_error", False)
        self.result = kw.get("result", "Bonjour")
        self.usage = kw.get("usage", {"output_tokens": 3})
        self.total_cost_usd = kw.get("total_cost_usd", 0.001)
        self.errors = kw.get("errors")


@pytest.fixture
def fake_sdk(monkeypatch):
    """A stand-in claude_agent_sdk module recording each query() call."""
    calls = []
    outcome = SimpleNamespace(messages=[_ResultMessage()], error=None)

    async def query(prompt, options):
        if not isinstance(prompt, str):
            prompt = [m async for m in prompt]
        calls.append({"prompt": prompt, "options": options})
        if outcome.error is not None:
            raise outcome.error
        for m in outcome.messages:
            yield m

    module = SimpleNamespace(
        query=query,
        ResultMessage=_ResultMessage,
        ClaudeAgentOptions=lambda **kw: SimpleNamespace(**kw),
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    monkeypatch.setattr(
        claude_module, "_claude_binary", lambda: "/usr/local/bin/claude"
    )
    return SimpleNamespace(calls=calls, outcome=outcome)


async def test_claude_text_completion(fake_sdk):
    result = await ClaudeProvider().complete(
        "claude-sonnet-5-5", CompletionRequest(user="Hi", system="Sys"), FULL
    )
    assert result.text == "Bonjour"
    assert result.usage == {"output_tokens": 3, "total_cost_usd": 0.001}
    [call] = fake_sdk.calls
    assert call["prompt"] == "Hi"
    opts = call["options"]
    assert (opts.model, opts.system_prompt, opts.allowed_tools, opts.max_turns) == (
        "claude-sonnet-5-5",
        "Sys",
        [],
        1,
    )
    assert opts.setting_sources == []
    # No tool, no MCP server, nothing pre-approved, the prompt taken verbatim.
    assert opts.tools == [] and opts.permission_mode == "dontAsk"
    assert opts.verbatim_prompts is True and opts.strict_mcp_config is True


async def test_claude_images_use_streaming_input(fake_sdk):
    await ClaudeProvider().complete(
        "claude-sonnet-5-5",
        CompletionRequest(user="Transcribe", images=[(b"img", "image/jpeg")]),
        FULL,
    )
    [message] = fake_sdk.calls[0]["prompt"]
    assert message["type"] == "user"
    image, text = message["message"]["content"]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": base64.b64encode(b"img").decode(),
    }
    assert text == {"type": "text", "text": "Transcribe"}


async def test_claude_error_result_raises(fake_sdk):
    fake_sdk.outcome.messages = [
        _ResultMessage(subtype="error_max_turns", is_error=True, errors=["boom"])
    ]
    with pytest.raises(ProviderError, match="boom"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), FULL)


async def test_claude_query_exception_raises(fake_sdk):
    fake_sdk.outcome.error = RuntimeError("cli crashed")
    with pytest.raises(ProviderError, match="cli crashed"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), FULL)


async def test_claude_no_result_raises(fake_sdk):
    fake_sdk.outcome.messages = []
    with pytest.raises(ProviderError, match="no result"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), FULL)


async def test_claude_unconfigured():
    with pytest.raises(ProviderError, match="Claude token"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), NONE)


async def test_claude_disabled_by_the_platform_flag(monkeypatch):
    monkeypatch.setattr(config, "enable_claude_provider", False)
    with pytest.raises(ProviderError):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), FULL)


async def test_claude_call_is_isolated_and_uses_only_the_callers_token(
    fake_sdk, monkeypatch
):
    monkeypatch.setenv(
        "ANTHROPIC_API_KEY", "sk-ant-api-SERVER-KEY-0000"
    )  # the operator's
    mine = make_creds(claude_token="sk-ant-oat01-alice-token")
    seen = {}

    async def query(prompt, options):
        seen["cwd_existed"] = os.path.isdir(options.cwd)  # noqa: ASYNC240 — a test
        seen["config_existed"] = os.path.isdir(  # noqa: ASYNC240 — a test
            options.env["CLAUDE_CONFIG_DIR"]
        )
        seen["options"] = options
        yield _ResultMessage()

    monkeypatch.setattr(sys.modules["claude_agent_sdk"], "query", query)
    await ClaudeProvider().complete(
        "claude-sonnet-5-5", CompletionRequest(user="u"), mine
    )

    options = seen["options"]
    env = options.env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-alice-token"
    # The server's own key must be blanked, or it would be merged over os.environ.
    assert env["ANTHROPIC_API_KEY"] == ""
    assert "DATABASE_URL" not in env and "SECRETS_ENCRYPTION_KEYS" not in env
    assert options.allowed_tools == [] and "Bash" in options.disallowed_tools
    assert options.setting_sources == []
    assert options.cli_path.endswith("claude-isolated")
    # A throwaway working and config directory, gone afterwards.
    assert seen["cwd_existed"] and seen["config_existed"]
    assert not os.path.exists(options.cwd)  # noqa: ASYNC240 — a test
    assert not os.path.exists(env["CLAUDE_CONFIG_DIR"])  # noqa: ASYNC240 — a test


async def test_claude_errors_are_scrubbed_of_tokens(fake_sdk):
    fake_sdk.outcome.error = RuntimeError(
        "auth failed for sk-ant-oat01-abcdefghijklmnop"
    )
    with pytest.raises(ProviderError) as info:
        await ClaudeProvider().complete("m", CompletionRequest(user="u"), FULL)
    assert "abcdefghijklmnop" not in str(info.value)


def test_the_wrapper_starts_the_cli_with_a_scrubbed_environment(tmp_path, monkeypatch):
    """Run the real launcher against a fake CLI that prints what it can see."""
    fake = tmp_path / "fake-claude"
    fake.write_text('#!/bin/sh\nenv\necho "ARGS=$*"\n')
    fake.chmod(0o755)
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://user:pw@db/app",
        "SECRETS_ENCRYPTION_KEYS": "k1:abc",
        "AUTH_SECRET_KEY": "server-secret",
        **claude_module.isolated_env(
            make_creds(claude_token="sk-ant-oat01-alice-token"),
            str(tmp_path),
            str(fake),
        ),
    }
    out = subprocess.run(  # noqa: S603 — runs the wrapper the test just built
        [claude_module._wrapper(), "--print", "hi there"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-alice-token" in out
    assert f"CLAUDE_CONFIG_DIR={tmp_path}" in out
    assert "ARGS=--print hi there" in out
    for leaked in (
        "DATABASE_URL",
        "SECRETS_ENCRYPTION_KEYS",
        "AUTH_SECRET_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert leaked not in out


# --- registry -----------------------------------------------------------------


async def test_complete_dispatches_on_prefix(fake_sdk):
    result = await complete(
        "claude:claude-sonnet-5-5", CompletionRequest(user="u"), FULL
    )
    assert result.text == "Bonjour"
    assert fake_sdk.calls[0]["options"].model == "claude-sonnet-5-5"


async def test_complete_wraps_unexpected_errors(monkeypatch):
    broken = MagicMock()
    broken.complete = AsyncMock(side_effect=KeyError("x"))
    monkeypatch.setitem(registry.PROVIDERS, "openai", broken)
    with pytest.raises(ProviderError, match="openai:m call failed"):
        await complete("openai:m", CompletionRequest(user="u"), FULL)
