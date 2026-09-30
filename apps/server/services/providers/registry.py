"""The single entry point for model calls: ``await complete(ref, request)``.

Callers pass a model reference (``"claude:claude-sonnet-5"``, see
:func:`server.services.providers.base.parse_ref`) and never touch a provider
SDK directly, so every text/vision call — cleaning, QA generation, file
transcription, the scheduled jobs — can run on either provider.
"""

import logging
import time
from typing import Dict, List

from server.services.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelInfo,
    Provider,
    ProviderError,
    make_ref,
    parse_ref,
)
from server.services.providers.claude import ClaudeProvider
from server.services.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

PROVIDERS: Dict[str, Provider] = {
    "openai": OpenAIProvider(),
    "claude": ClaudeProvider(),
}


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ProviderError(f"Unknown model provider '{name}'") from None


def normalize_ref(ref: str) -> str:
    """Always the prefixed form: a bare ``gpt-4o`` becomes ``openai:gpt-4o``."""
    provider, model = parse_ref(ref)
    return make_ref(provider, model)


def validate_ref(ref: str) -> str:
    """The normalized reference; ValueError naming what is wrong otherwise."""
    provider_name, model = parse_ref(ref)
    if not model:
        raise ValueError(f"Model reference '{ref}' has no model id")
    provider = get_provider(provider_name)
    if not provider.configured():
        raise ValueError(
            f"Provider '{provider_name}' is not configured — set "
            + ", ".join(provider.missing_env())
        )
    if not provider.knows(model):
        known = ", ".join(m.ref for m in provider.models()) or "none"
        raise ValueError(f"Unknown model '{ref}'. Available: {known}")
    return make_ref(provider_name, model)


def all_models() -> List[ModelInfo]:
    return [m for p in PROVIDERS.values() for m in p.models()]


async def complete(ref: str, req: CompletionRequest) -> CompletionResult:
    """Run one completion on the provider ``ref`` points at.

    Raises :class:`ProviderError` for an unknown/unconfigured provider or a
    failed call — callers decide whether that degrades or aborts.
    """
    provider_name, model = parse_ref(ref)
    provider = get_provider(provider_name)
    started = time.perf_counter()
    try:
        result = await provider.complete(model, req)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"{provider_name}:{model} call failed: {exc}") from exc
    logger.info(
        "%s:%s completion in %.1fs (%d chars%s)",
        provider_name,
        model,
        time.perf_counter() - started,
        len(result.text),
        f", {len(req.images)} image(s)" if req.images else "",
    )
    return result
