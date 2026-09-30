"""Shared types for the model providers.

A model is addressed by a *reference* ``"<provider>:<model id>"`` — e.g.
``openai:gpt-4o-mini`` or ``claude:claude-sonnet-5``. A bare id (no prefix)
means the OpenAI-compatible provider, so the ``OPENAI_*_MODEL`` values that
predate providers keep working unchanged.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

DEFAULT_PROVIDER = "openai"
PROVIDER_NAMES = ("openai", "claude")


class ProviderError(RuntimeError):
    """A provider is unknown, unconfigured, or its call failed."""


@dataclass(frozen=True)
class ModelInfo:
    ref: str
    id: str
    provider: str
    label: str
    vision: bool = False


@dataclass
class CompletionRequest:
    """One single-turn completion: system + user text, optional images."""

    user: str
    system: str = ""
    max_tokens: int = 4000
    # (raw bytes, mime type) per image, sent before the user text.
    images: List[Tuple[bytes, str]] = field(default_factory=list)
    # Long structured generations (the QA agent): lets the OpenAI provider send
    # OPENAI_REASONING_EFFORT so reasoning models reach the final JSON.
    reasoning: bool = False


@dataclass
class CompletionResult:
    text: str
    # Provider-reported usage (tokens, cost) when available — for the Models
    # page and logs, never for billing decisions.
    usage: Optional[Dict[str, Any]] = None


class Provider(Protocol):
    name: str
    label: str

    def configured(self) -> bool: ...

    def missing_env(self) -> List[str]: ...

    def models(self) -> List[ModelInfo]: ...

    async def list_models(self) -> List[ModelInfo]: ...

    def knows(self, model_id: str) -> bool: ...

    async def complete(
        self, model: str, req: CompletionRequest
    ) -> CompletionResult: ...


def parse_ref(ref: str) -> Tuple[str, str]:
    """``"claude:claude-sonnet-5"`` → ``("claude", "claude-sonnet-5")``.

    A bare id belongs to :data:`DEFAULT_PROVIDER`. Only the first ``:`` splits,
    and only when the prefix is a known provider name — some OpenAI-compatible
    hosts use ``:`` inside model ids (``llama3:8b``).
    """
    ref = (ref or "").strip()
    prefix, sep, rest = ref.partition(":")
    if sep and prefix in PROVIDER_NAMES:
        return prefix, rest
    return DEFAULT_PROVIDER, ref


def make_ref(provider: str, model: str) -> str:
    return f"{provider}:{model}"
