"""OpenAI-compatible provider (OPENAI_API_KEY / OPENAI_BASE_URL).

Any endpoint speaking the chat-completions API works — OpenAI itself, or a
self-hosted/managed gateway. Images are sent as ``image_url`` data URIs.
"""

import asyncio
import base64
import functools
import logging
from typing import Any, Dict, List

from server.core.config import config
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


class OpenAIProvider:
    name = "openai"
    label = "OpenAI API"

    def __init__(self) -> None:
        # Ids seen by the last successful discovery — accepted by validation
        # on top of the configured ones.
        self._discovered: List[str] = []

    @functools.cached_property
    def client(self) -> Any:
        # Lazy: building the client touches SSL/certifi, which some sandboxes
        # block — constructing the provider must stay free.
        import openai

        return openai.AsyncOpenAI(
            api_key=config.openai_api_key, base_url=config.openai_base_url or None
        )

    def configured(self) -> bool:
        return bool(config.openai_api_key)

    def missing_env(self) -> List[str]:
        return [] if self.configured() else ["OPENAI_API_KEY"]

    def _info(self, model_id: str) -> ModelInfo:
        return ModelInfo(
            ref=make_ref(self.name, model_id),
            id=model_id,
            provider=self.name,
            label=model_id,
            vision=model_id == config.openai_vlm_model,
        )

    def models(self) -> List[ModelInfo]:
        """Configured models first, then any discovered on the endpoint."""
        ids = list(dict.fromkeys([*config.available_models, *self._discovered]))
        return [self._info(i) for i in ids]

    async def list_models(self) -> List[ModelInfo]:
        """:meth:`models`, refreshed from the endpoint's ``/models`` when it answers."""
        if self.configured():
            try:
                page = await asyncio.wait_for(
                    self.client.models.list(), timeout=_DISCOVERY_TIMEOUT_S
                )
                self._discovered = sorted(m.id for m in page.data)
            except Exception as exc:  # noqa: BLE001 — discovery is best-effort
                logger.warning("OpenAI model discovery failed: %s", exc)
        return self.models()

    def knows(self, model_id: str) -> bool:
        return model_id in config.available_models or model_id in self._discovered

    async def complete(self, model: str, req: CompletionRequest) -> CompletionResult:
        if not self.configured():
            raise ProviderError("OpenAI provider is not configured (OPENAI_API_KEY)")
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
        response = await self.client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        usage = (
            response.usage.model_dump() if getattr(response, "usage", None) else None
        )
        return CompletionResult(text=text, usage=usage)
