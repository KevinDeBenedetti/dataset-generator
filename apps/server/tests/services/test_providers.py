"""Model providers: reference parsing, validation, and both providers' calls
(OpenAI client and Claude Agent SDK mocked — no network, no Claude Code)."""

import base64
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.core.config import config
from server.services.providers import (
    CompletionRequest,
    ProviderError,
    complete,
    normalize_ref,
    parse_ref,
    validate_ref,
)
from server.services.providers import registry
from server.services.providers.claude import ClaudeProvider
from server.services.providers.openai import OpenAIProvider


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("claude:claude-sonnet-5", ("claude", "claude-sonnet-5")),
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
        monkeypatch.setattr(config, "openai_api_key", "k")
        monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
        assert validate_ref("gpt-4o-mini") == "openai:gpt-4o-mini"

    def test_unknown_model(self, monkeypatch):
        monkeypatch.setattr(config, "openai_api_key", "k")
        monkeypatch.setattr(config, "available_models", ["gpt-4o-mini"])
        with pytest.raises(ValueError, match="Unknown model 'openai:nope'"):
            validate_ref("openai:nope")

    def test_unconfigured_provider(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="CLAUDE_CODE_OAUTH_TOKEN"):
            validate_ref("claude:claude-sonnet-5")

    def test_claude_models_override(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
        monkeypatch.setattr(config, "claude_models_raw", "claude-x, claude-y")
        assert validate_ref("claude:claude-y") == "claude:claude-y"
        with pytest.raises(ValueError):
            validate_ref("claude:claude-sonnet-5")

    def test_empty_model(self):
        with pytest.raises(ValueError, match="no model id"):
            validate_ref("claude:")


# --- OpenAI -------------------------------------------------------------------


def _openai_provider(monkeypatch, text="Hello"):
    monkeypatch.setattr(config, "openai_api_key", "k")
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
    provider.__dict__["client"] = client  # prime the cached_property
    return provider, client


async def test_openai_text_completion(monkeypatch):
    provider, client = _openai_provider(monkeypatch)
    result = await provider.complete(
        "gpt-x", CompletionRequest(user="Hi", system="Sys")
    )
    assert result.text == "Hello" and result.usage == {"total_tokens": 7}
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-x"
    assert kwargs["messages"] == [
        {"role": "system", "content": "Sys"},
        {"role": "user", "content": "Hi"},
    ]
    assert "reasoning_effort" not in kwargs


async def test_openai_image_payload(monkeypatch):
    provider, client = _openai_provider(monkeypatch)
    await provider.complete(
        "vlm", CompletionRequest(user="Transcribe", images=[(b"img", "image/png")])
    )
    content = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert (
        content[0]["image_url"]["url"]
        == "data:image/png;base64," + base64.b64encode(b"img").decode()
    )
    assert content[-1] == {"type": "text", "text": "Transcribe"}


@pytest.mark.parametrize("effort, sent", [("low", True), ("", False)])
async def test_openai_reasoning_effort(monkeypatch, effort, sent):
    provider, client = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "openai_reasoning_effort", effort)
    await provider.complete("m", CompletionRequest(user="u", reasoning=True))
    kwargs = client.chat.completions.create.call_args.kwargs
    assert ("reasoning_effort" in kwargs) is sent


async def test_openai_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "openai_api_key", "")
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        await OpenAIProvider().complete("m", CompletionRequest(user="u"))


async def test_openai_discovery_is_best_effort(monkeypatch):
    provider, client = _openai_provider(monkeypatch)
    monkeypatch.setattr(config, "available_models", ["configured"])
    client.models.list = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id="live")])
    )
    assert [m.id for m in await provider.list_models()] == ["configured", "live"]
    assert provider.knows("live")

    client.models.list = AsyncMock(side_effect=RuntimeError("down"))
    assert [m.id for m in await provider.list_models()] == ["configured", "live"]


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
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    return SimpleNamespace(calls=calls, outcome=outcome)


async def test_claude_text_completion(fake_sdk):
    result = await ClaudeProvider().complete(
        "claude-sonnet-5", CompletionRequest(user="Hi", system="Sys")
    )
    assert result.text == "Bonjour"
    assert result.usage == {"output_tokens": 3, "total_cost_usd": 0.001}
    [call] = fake_sdk.calls
    assert call["prompt"] == "Hi"
    opts = call["options"]
    assert (opts.model, opts.system_prompt, opts.allowed_tools, opts.max_turns) == (
        "claude-sonnet-5",
        "Sys",
        [],
        1,
    )
    assert opts.setting_sources == []


async def test_claude_images_use_streaming_input(fake_sdk):
    await ClaudeProvider().complete(
        "claude-sonnet-5",
        CompletionRequest(user="Transcribe", images=[(b"img", "image/jpeg")]),
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
        await ClaudeProvider().complete("m", CompletionRequest(user="u"))


async def test_claude_query_exception_raises(fake_sdk):
    fake_sdk.outcome.error = RuntimeError("cli crashed")
    with pytest.raises(ProviderError, match="cli crashed"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"))


async def test_claude_no_result_raises(fake_sdk):
    fake_sdk.outcome.messages = []
    with pytest.raises(ProviderError, match="no result"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"))


async def test_claude_unconfigured(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        await ClaudeProvider().complete("m", CompletionRequest(user="u"))


# --- registry -----------------------------------------------------------------


async def test_complete_dispatches_on_prefix(fake_sdk):
    result = await complete("claude:claude-sonnet-5", CompletionRequest(user="u"))
    assert result.text == "Bonjour"
    assert fake_sdk.calls[0]["options"].model == "claude-sonnet-5"


async def test_complete_wraps_unexpected_errors(monkeypatch):
    broken = MagicMock()
    broken.complete = AsyncMock(side_effect=KeyError("x"))
    monkeypatch.setitem(registry.PROVIDERS, "openai", broken)
    with pytest.raises(ProviderError, match="openai:m call failed"):
        await complete("openai:m", CompletionRequest(user="u"))
