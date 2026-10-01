"""OpenAI-compatible provider, on the caller's own API key and endpoint.

Any endpoint speaking the chat-completions API works — OpenAI itself, or a
self-hosted/managed gateway. Images are sent as ``image_url`` data URIs.
"""

import asyncio
import base64
import hashlib
import logging
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

from server.core import net
from server.core.config import config
from server.services import platform
from server.services.credentials import OPENAI_API_KEY, Credentials
from server.services.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelInfo,
    ProviderError,
    make_ref,
)

logger = logging.getLogger(__name__)

# Live model discovery must never hold up a page load.
_DISCOVERY_TIMEOUT_S = 5.0
_REQUEST_TIMEOUT_S = 120.0
_DISCOVERY_TTL_S = 300.0


def check_base_url(url: str) -> str:
    """A user-typed base URL, or ValueError. Static rules only (https, allowed host);
    the DNS/address check runs on every request (core/net.PinnedTransport)."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("The base URL must be an https URL")
    if parts.username or parts.password:
        raise ValueError("The base URL must not contain credentials")
    host = parts.hostname.lower().rstrip(".")
    allowed = platform.allowed_llm_hosts()
    if not platform.allow_custom_base_url() and host not in allowed:
        raise ValueError(
            f"{host} is not an allowed endpoint (allowed: {', '.join(allowed)})"
        )
    return url


def _cache_key(creds: Credentials) -> str:
    """Identifies a key+endpoint for the discovery cache without keeping the key."""
    material = f"{creds.openai_base_url}|{creds.secret(OPENAI_API_KEY)}"
    return hashlib.sha256(material.encode()).hexdigest()


class OpenAIProvider:
    name = "openai"
    label = "OpenAI API"

    def __init__(self) -> None:
        # Model ids seen by a successful discovery, per key+endpoint (hashed), so
        # one user's account never shapes another's list.
        self._discovered: Dict[str, Tuple[float, List[str]]] = {}

    def build_client(self, creds: Credentials) -> Any:
        # Built per call from the caller's credentials — nothing is shared or
        # cached between users. Lazy import: building the client touches
        # SSL/certifi, which some sandboxes block.
        import openai

        kwargs: Dict[str, Any] = {
            "api_key": creds.secret(OPENAI_API_KEY),
            "base_url": creds.openai_base_url or None,
        }
        if not creds.base_url_trusted:
            # A user-chosen endpoint: public addresses only, pinned at connect.
            if creds.openai_base_url:
                check_base_url(creds.openai_base_url)
            allowed = (
                None
                if platform.allow_custom_base_url()
                else platform.allowed_llm_hosts()
            )
            kwargs["http_client"] = net.pinned_client(
                timeout=_REQUEST_TIMEOUT_S, allowed_hosts=allowed
            )
        return openai.AsyncOpenAI(**kwargs)

    def configured(self, creds: Credentials) -> bool:
        return creds.has(OPENAI_API_KEY)

    def missing(self, creds: Credentials) -> List[str]:
        return [] if self.configured(creds) else ["your OpenAI API key"]

    def _info(self, model_id: str) -> ModelInfo:
        return ModelInfo(
            ref=make_ref(self.name, model_id),
            id=model_id,
            provider=self.name,
            label=model_id,
            vision=model_id == config.openai_vlm_model,
        )

    def _ids(self, creds: Credentials) -> List[str]:
        cached = self._discovered.get(_cache_key(creds))
        seen = cached[1] if cached else []  # stale ids stay valid
        return list(dict.fromkeys([*config.available_models, *seen]))

    def models(self, creds: Credentials) -> List[ModelInfo]:
        """Configured models first, then any discovered on the caller's endpoint."""
        return [self._info(i) for i in self._ids(creds)]

    async def list_models(self, creds: Credentials) -> List[ModelInfo]:
        """:meth:`models`, refreshed from the endpoint's ``/models`` when it answers."""
        key = _cache_key(creds)
        cached = self._discovered.get(key)
        if self.configured(creds) and not (
            cached and time.monotonic() - cached[0] < _DISCOVERY_TTL_S
        ):
            try:
                async with self.build_client(creds) as client:
                    page = await asyncio.wait_for(
                        client.models.list(), timeout=_DISCOVERY_TIMEOUT_S
                    )
                self._discovered[key] = (
                    time.monotonic(),
                    sorted(m.id for m in page.data),
                )
            except Exception as exc:  # noqa: BLE001 — discovery is best-effort
                logger.warning("OpenAI model discovery failed: %s", type(exc).__name__)
        return self.models(creds)

    def knows(self, model_id: str, creds: Credentials) -> bool:
        return model_id in self._ids(creds)

    async def complete(
        self, model: str, req: CompletionRequest, creds: Credentials
    ) -> CompletionResult:
        if not self.configured(creds):
            raise ProviderError("OpenAI provider is not configured — add your API key")
        content: Any = req.user
        if req.images:
            content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,"
                        + base64.b64encode(data).decode("ascii")
                    },
                }
                for data, mime in req.images
            ] + [{"type": "text", "text": req.user}]
        messages: List[Dict[str, Any]] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": content})

        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=config.temperature,
        )
        # "low" keeps gpt-oss-style reasoning models from spending their whole
        # budget thinking; OPENAI_REASONING_EFFORT=off for models rejecting it.
        if req.reasoning and config.openai_reasoning_effort:
            kwargs["reasoning_effort"] = config.openai_reasoning_effort
        async with self.build_client(creds) as client:
            response = await client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        usage = (
            response.usage.model_dump() if getattr(response, "usage", None) else None
        )
        return CompletionResult(text=text, usage=usage)
