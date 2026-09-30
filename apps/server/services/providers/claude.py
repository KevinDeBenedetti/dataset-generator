"""Claude subscription provider, through the Claude Agent SDK.

Authenticated with CLAUDE_CODE_OAUTH_TOKEN (``claude setup-token``) so calls
bill against a Claude Pro/Max subscription — that subscription grants no plain
API access, only Claude Code, which is what the SDK drives (ANTHROPIC_API_KEY
works too, billed per token). The SDK bundles the Claude Code binary, so it
lives in the ``jobs`` dependency group (included in the server image).

Each call is a plain single-turn generation: no tools, no filesystem settings
(never picking up a CLAUDE.md or hooks from the working directory). Images go
through the SDK's streaming-input mode, as ``image`` content blocks.
"""

import base64
import logging
from typing import Any, AsyncIterator, Dict, List

from server.core.config import _env, config
from server.services.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelInfo,
    ProviderError,
    make_ref,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELS = ("claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001")


class ClaudeProvider:
    name = "claude"
    label = "Claude subscription"

    def configured(self) -> bool:
        return bool(_env("CLAUDE_CODE_OAUTH_TOKEN") or _env("ANTHROPIC_API_KEY"))

    def missing_env(self) -> List[str]:
        return [] if self.configured() else ["CLAUDE_CODE_OAUTH_TOKEN"]

    def _ids(self) -> List[str]:
        custom = [m.strip() for m in config.claude_models_raw.split(",") if m.strip()]
        return custom or list(DEFAULT_MODELS)

    def models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                ref=make_ref(self.name, i),
                id=i,
                provider=self.name,
                label=i,
                vision=True,
            )
            for i in self._ids()
        ]

    async def list_models(self) -> List[ModelInfo]:
        return self.models()

    def knows(self, model_id: str) -> bool:
        return model_id in self._ids()

    @staticmethod
    def _prompt(req: CompletionRequest) -> Any:
        """A plain string, or a one-message stream when images are attached."""
        if not req.images:
            return req.user
        content: List[Dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
            for data, mime in req.images
        ]
        content.append({"type": "text", "text": req.user})

        async def stream() -> AsyncIterator[Dict[str, Any]]:
            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
                "parent_tool_use_id": None,
            }

        return stream()

    async def complete(self, model: str, req: CompletionRequest) -> CompletionResult:
        if not self.configured():
            raise ProviderError(
                "Claude provider is not configured (CLAUDE_CODE_OAUTH_TOKEN)"
            )
        try:
            from claude_agent_sdk import (  # ty: ignore[unresolved-import]
                ClaudeAgentOptions,
                ResultMessage,
                query,
            )
        except ImportError as exc:
            raise ProviderError(
                "claude-agent-sdk is not installed (uv sync --group jobs)"
            ) from exc

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=req.system or None,
            allowed_tools=[],
            setting_sources=[],
            max_turns=1,
        )
        result = None
        try:
            async for message in query(prompt=self._prompt(req), options=options):
                if isinstance(message, ResultMessage):
                    result = message
        except Exception as exc:
            raise ProviderError(f"Claude query failed: {exc}") from exc

        if result is None:
            raise ProviderError("Claude query returned no result")
        if result.is_error or result.subtype != "success":
            detail = "; ".join(result.errors or []) or result.subtype
            raise ProviderError(f"Claude query failed: {detail}")
        usage = dict(result.usage or {})
        if result.total_cost_usd is not None:
            usage["total_cost_usd"] = result.total_cost_usd
        return CompletionResult(text=(result.result or "").strip(), usage=usage or None)
