"""OpenAI-compatible provider: chat completions and embeddings on one endpoint.

Any endpoint speaking the OpenAI API works — OpenAI itself, or a gateway such
as LiteLLM, vLLM or Ollama. The endpoint and its key always travel together
(``Credentials``): the caller's own pair, or the operator's ``OPENAI_BASE_URL``
+ ``OPENAI_API_KEY`` where the server lends them (services/credentials.py).
Images are sent as ``image_url`` data URIs.

Discovery (``GET /models`` on the endpoint) sorts what it serves into chat and
embedding models — by LiteLLM's ``/model/info`` (the ``mode`` of each alias)
when the endpoint answers it, by the model ids otherwise. The chat models are
offered for the model roles, the embedding ones to the vector collections.
"""

import asyncio
import base64
import hashlib
import logging
import time
from typing import Any, Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

from server.core import net
from server.core.config import config
from server.core.redact import redact
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
# An endpoint that didn't answer is asked again after this long, not on every
# page load (each attempt can wait the whole timeout).
_DISCOVERY_RETRY_S = 60.0

# Embedding requests: texts per request and characters per request (OpenAI
# takes 2048 inputs and 300k tokens; gateways often less), and per text — about
# 8k tokens even for scripts of one token per character.
EMBED_BATCH = 128
EMBED_BATCH_CHARS = 120_000
EMBED_MAX_CHARS = 8_000

# What a discovered model is for.
CHAT, EMBEDDING, OTHER = "chat", "embedding", "other"
# By id, when the endpoint doesn't say: OpenAI's text-embedding-*, a gateway's
# embed-* aliases and the open embedding families; and the models that are
# neither (moderation, speech, images, reranking).
_EMBEDDING_HINTS = ("embed", "bge-", "e5-", "gte-", "minilm")
_OTHER_HINTS = (
    "moderation",
    "whisper",
    "tts",
    "dall-e",
    "gpt-image",
    "rerank",
    "transcribe",
    "sora",
)
# LiteLLM's model_info.mode values that take chat completions.
_CHAT_MODES = ("chat", "completion", "responses")


def classify_model_id(model_id: str) -> str:
    """:data:`CHAT`, :data:`EMBEDDING` or :data:`OTHER`, guessed from the id."""
    lowered = model_id.lower()
    if any(hint in lowered for hint in _OTHER_HINTS):
        return OTHER
    if any(hint in lowered for hint in _EMBEDDING_HINTS):
        return EMBEDDING
    return CHAT


def _kind_of_mode(mode: str) -> str:
    if mode in _CHAT_MODES:
        return CHAT
    return EMBEDDING if mode == "embedding" else OTHER


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


def connection_key(creds: Credentials) -> str:
    """Identifies a key+endpoint for the caches without keeping the key."""
    material = f"{creds.openai_base_url}|{creds.secret(OPENAI_API_KEY)}"
    return hashlib.sha256(material.encode()).hexdigest()


async def _model_modes(client: Any) -> Dict[str, str]:
    """``{alias: mode}`` from LiteLLM's ``/model/info``; ``{}`` from any other
    endpoint (OpenAI answers 404) — the ids decide then."""
    try:
        info = await client.get("/model/info", cast_to=object)
    except Exception:  # noqa: BLE001 — optional, LiteLLM only
        return {}
    modes: Dict[str, str] = {}
    entries = info.get("data") if isinstance(info, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name")
        mode = (entry.get("model_info") or {}).get("mode")
        # An alias with several deployments is listed once per deployment.
        if isinstance(name, str) and isinstance(mode, str) and name not in modes:
            modes[name] = mode
    return modes


class OpenAIProvider:
    name = "openai"
    label = "OpenAI-compatible"

    def __init__(self) -> None:
        # What a discovery found, per key+endpoint (hashed), so one user's
        # account never shapes another's list: (when, chat ids, embedding ids).
        self._discovered: Dict[str, Tuple[float, List[str], List[str]]] = {}
        # When a discovery last failed, per key+endpoint.
        self._failed: Dict[str, float] = {}

    def _client_kwargs(self, creds: Credentials, sync: bool) -> Dict[str, Any]:
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
            make = net.pinned_sync_client if sync else net.pinned_client
            kwargs["http_client"] = make(
                timeout=_REQUEST_TIMEOUT_S, allowed_hosts=allowed
            )
        return kwargs

    def build_client(self, creds: Credentials) -> Any:
        # Built per call from the caller's credentials — nothing is shared or
        # cached between users. Lazy import: building the client touches
        # SSL/certifi, which some sandboxes block.
        import openai

        return openai.AsyncOpenAI(**self._client_kwargs(creds, sync=False))

    def build_sync_client(self, creds: Credentials) -> Any:
        """:meth:`build_client` for the embeddings, which run in threads."""
        import openai

        return openai.OpenAI(**self._client_kwargs(creds, sync=True))

    def configured(self, creds: Credentials) -> bool:
        return creds.has(OPENAI_API_KEY)

    def missing(self, creds: Credentials) -> List[str]:
        return [] if self.configured(creds) else ["your API key (and endpoint)"]

    def endpoint(self, creds: Credentials) -> str:
        """The host the calls go to (for display)."""
        url = (creds.openai_base_url or "").strip()
        return (urlsplit(url).hostname or url) if url else "api.openai.com"

    def lent(self, creds: Credentials) -> bool:
        """The calls use the server's key and endpoint, not the caller's own."""
        return creds.openai_from_server and self.configured(creds)

    def _info(self, model_id: str) -> ModelInfo:
        return ModelInfo(
            ref=make_ref(self.name, model_id),
            id=model_id,
            provider=self.name,
            label=model_id,
        )

    def _ids(self, creds: Credentials) -> List[str]:
        """The chat models: configured first, then the discovered ones."""
        cached = self._discovered.get(connection_key(creds))
        seen = cached[1] if cached else []  # stale ids stay valid
        return list(
            dict.fromkeys(
                [
                    *config.available_models,
                    *(i for i in seen if i != config.openai_embedding_model),
                ]
            )
        )

    def _embedding_ids(self, creds: Credentials) -> List[str]:
        cached = self._discovered.get(connection_key(creds))
        seen = cached[2] if cached else []
        configured = (
            [config.openai_embedding_model] if config.openai_embedding_model else []
        )
        return list(dict.fromkeys([*configured, *seen]))

    def models(self, creds: Credentials) -> List[ModelInfo]:
        """Chat models: configured first, then any discovered on the caller's endpoint."""
        return [self._info(i) for i in self._ids(creds)]

    def embedding_models(self, creds: Credentials) -> List[ModelInfo]:
        """Embedding models: OPENAI_EMBEDDING_MODEL first, then any discovered."""
        if not self.configured(creds):
            return []
        return [
            ModelInfo(ref=make_ref(self.name, i), id=i, provider=self.name, label=i)
            for i in self._embedding_ids(creds)
        ]

    async def list_models(self, creds: Credentials) -> List[ModelInfo]:
        """:meth:`models`, refreshed from the endpoint's ``/models`` when it answers."""
        await self.discover(creds)
        return self.models(creds)

    async def discover(self, creds: Credentials) -> None:
        """Ask the endpoint what it serves (best-effort, cached per key+endpoint)."""
        if not self.configured(creds):
            return
        key = connection_key(creds)
        now = time.monotonic()
        cached = self._discovered.get(key)
        if cached and now - cached[0] < _DISCOVERY_TTL_S:
            return
        failed_at = self._failed.get(key)
        if failed_at is not None and now - failed_at < _DISCOVERY_RETRY_S:
            return
        try:
            async with self.build_client(creds) as client:
                page, modes = await asyncio.wait_for(
                    asyncio.gather(client.models.list(), _model_modes(client)),
                    timeout=_DISCOVERY_TIMEOUT_S,
                )
        except Exception as exc:  # noqa: BLE001 — discovery is best-effort
            self._failed[key] = time.monotonic()
            logger.warning("Model discovery failed: %s", type(exc).__name__)
            return
        chat: List[str] = []
        embedding: List[str] = []
        for model_id in sorted({m.id for m in page.data}):
            mode = modes.get(model_id)
            kind = _kind_of_mode(mode) if mode else classify_model_id(model_id)
            if kind == CHAT:
                chat.append(model_id)
            elif kind == EMBEDDING:
                embedding.append(model_id)
        self._discovered[key] = (time.monotonic(), chat, embedding)
        self._failed.pop(key, None)

    def knows(self, model_id: str, creds: Credentials) -> bool:
        return model_id in self._ids(creds)

    async def complete(
        self, model: str, req: CompletionRequest, creds: Credentials
    ) -> CompletionResult:
        if not self.configured(creds):
            raise ProviderError(
                "The OpenAI-compatible provider is not configured — add your API key"
            )
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

        kwargs: Dict[str, Any] = dict(model=model, messages=messages)
        # Reasoning models (o-series, gpt-5): the budget goes as
        # max_completion_tokens (they refuse max_tokens), the temperature stays
        # theirs (they refuse any other), and "low" keeps gpt-oss-style ones
        # from spending the whole budget thinking. OPENAI_REASONING_EFFORT=off
        # for models rejecting the parameter: the classic shape goes out then,
        # which every OpenAI-compatible endpoint takes.
        if req.reasoning and config.openai_reasoning_effort:
            kwargs["max_completion_tokens"] = req.max_tokens
            kwargs["reasoning_effort"] = config.openai_reasoning_effort
        else:
            kwargs["max_tokens"] = req.max_tokens
            kwargs["temperature"] = config.temperature
        async with self.build_client(creds) as client:
            response = await client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        usage = (
            response.usage.model_dump() if getattr(response, "usage", None) else None
        )
        return CompletionResult(text=text, usage=usage)

    def embed(
        self, model: str, texts: Sequence[str], creds: Credentials
    ) -> List[List[float]]:
        """One vector per text, in order. Blocking: callers run it in a thread.

        A text is cut at :data:`EMBED_MAX_CHARS`, and an empty one sent as a
        space (the API refuses empty strings). ProviderError on any failure.
        """
        if not self.configured(creds):
            raise ProviderError(
                "The OpenAI-compatible provider is not configured — add your API key"
            )
        inputs = [(t or "").strip()[:EMBED_MAX_CHARS] or " " for t in texts]
        batches: List[List[str]] = []
        for text in inputs:
            if (
                not batches
                or len(batches[-1]) >= EMBED_BATCH
                or sum(map(len, batches[-1])) + len(text) > EMBED_BATCH_CHARS
            ):
                batches.append([])
            batches[-1].append(text)
        vectors: List[List[float]] = []
        try:
            with self.build_sync_client(creds) as client:
                for batch in batches:
                    response = client.embeddings.create(
                        model=model, input=batch, encoding_format="float"
                    )
                    # The API keeps the input order; sort by index regardless.
                    data = sorted(response.data, key=lambda d: d.index)
                    if len(data) != len(batch):
                        raise ProviderError(
                            f"{len(data)} embeddings for {len(batch)} texts"
                        )
                    vectors.extend(list(d.embedding) for d in data)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"{self.name}:{model} embedding failed: {redact(str(exc))}"
            ) from exc
        return vectors
