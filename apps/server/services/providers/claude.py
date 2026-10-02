"""Claude subscription provider, through the Claude Agent SDK.

Authenticated with the caller's own token (``claude setup-token``, billed to
their Claude Pro/Max subscription) or Anthropic API key. The SDK bundles the
Claude Code binary, so it lives in the ``jobs`` dependency group (included in
the server image).

**The subprocess is isolated.** The SDK merges its ``env`` over ``os.environ``,
so without care the Claude process — which a prompt-injected page could steer —
would inherit the server's database URL and encryption keys. Every call
therefore runs the CLI through a small wrapper that starts it under ``env -i``
with only PATH, a throwaway HOME/config directory and the caller's own token,
in an empty temporary working directory that is deleted afterwards.

Each call is a plain single-turn generation: no tools, no filesystem settings
(never picking up a CLAUDE.md or hooks from the working directory). Images go
through the SDK's streaming-input mode, as ``image`` content blocks.
"""

import base64
import logging
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from server.core.config import config
from server.core.redact import redact
from server.services.credentials import ANTHROPIC_API_KEY, CLAUDE_TOKEN, Credentials
from server.services.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelInfo,
    ProviderError,
    make_ref,
)

logger = logging.getLogger(__name__)

DEFAULT_MODELS = ("claude-opus-5-5", "claude-sonnet-5", "claude-haiku-4-5-20251001")


# Tools the agent could otherwise reach; a plain completion needs none of them.
_BUILTIN_TOOLS = [
    "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit",
    "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
    "SlashCommand", "ExitPlanMode",
]  # fmt: skip

_WRAPPER = """#!/bin/sh
# Runs the Claude CLI with a scrubbed environment (see services/providers/claude.py).
exec /usr/bin/env -i \\
  PATH="${PATH:-/usr/bin:/bin}" \\
  HOME="$CLAUDE_CONFIG_DIR" \\
  CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR" \\
  ${CLAUDE_CODE_OAUTH_TOKEN:+CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"} \\
  ${ANTHROPIC_API_KEY:+ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"} \\
  DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 \\
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \\
  "$DATASETGEN_CLAUDE_BIN" "$@"
"""

_wrapper_path: Optional[Path] = None


def _wrapper() -> str:
    """The env-scrubbing launcher, written once per process into a private directory."""
    global _wrapper_path
    if _wrapper_path is None or not _wrapper_path.exists():
        directory = Path(tempfile.mkdtemp(prefix="datasetgen-claude-"))
        directory.chmod(stat.S_IRWXU)
        path = directory / "claude-isolated"
        path.write_text(_WRAPPER)
        path.chmod(stat.S_IRWXU)
        _wrapper_path = path
    return str(_wrapper_path)


def _claude_binary() -> str:
    """The real Claude Code binary: the SDK's bundled copy, else ``claude`` on PATH."""
    try:
        import claude_agent_sdk  # ty: ignore[unresolved-import]

        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        if bundled.exists():
            return str(bundled)
    except ImportError:
        pass
    found = shutil.which("claude")
    if found:
        return found
    raise ProviderError("The Claude CLI was not found on the server")


def isolated_env(creds: Credentials, config_dir: str, binary: str) -> Dict[str, str]:
    """The ``env`` handed to the SDK for one call.

    Both credential variables are always set — to "" when unused — so a value in
    the server's own environment can never be picked up (and billed) instead of
    the caller's; the wrapper drops empty ones.
    """
    token = creds.secret(CLAUDE_TOKEN)
    api_key = "" if token else creds.secret(ANTHROPIC_API_KEY)
    return {
        "CLAUDE_CODE_OAUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": api_key,
        "CLAUDE_CONFIG_DIR": config_dir,
        "DATASETGEN_CLAUDE_BIN": binary,
    }


class ClaudeProvider:
    name = "claude"
    label = "Claude subscription"

    def configured(self, creds: Credentials) -> bool:
        return config.claude_provider_available and (
            creds.has(CLAUDE_TOKEN) or creds.has(ANTHROPIC_API_KEY)
        )

    def missing(self, creds: Credentials) -> List[str]:
        if not config.claude_provider_available:
            return ["(the Claude provider is only available in development and CI)"]
        if self.configured(creds):
            return []
        return ["your Claude token (`claude setup-token`) or Anthropic API key"]

    def _ids(self) -> List[str]:
        custom = [m.strip() for m in config.claude_models_raw.split(",") if m.strip()]
        return custom or list(DEFAULT_MODELS)

    def models(self, creds: Credentials) -> List[ModelInfo]:
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

    async def list_models(self, creds: Credentials) -> List[ModelInfo]:
        return self.models(creds)

    def knows(self, model_id: str, creds: Credentials) -> bool:
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

    async def complete(
        self, model: str, req: CompletionRequest, creds: Credentials
    ) -> CompletionResult:
        if not self.configured(creds):
            raise ProviderError(
                "Claude provider is not configured — add your Claude token in Settings"
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

        binary = _claude_binary()
        scratch = tempfile.mkdtemp(prefix="claude-call-")
        try:
            config_dir = Path(scratch, "config")
            workdir = Path(scratch, "cwd")
            config_dir.mkdir(mode=0o700)
            workdir.mkdir(mode=0o700)
            options = ClaudeAgentOptions(
                model=model,
                system_prompt=req.system or None,
                allowed_tools=[],
                disallowed_tools=_BUILTIN_TOOLS,
                setting_sources=[],
                max_turns=1,
                cwd=str(workdir),
                cli_path=_wrapper(),
                env=isolated_env(creds, str(config_dir), binary),
            )
            result = None
            try:
                async for message in query(prompt=self._prompt(req), options=options):
                    if isinstance(message, ResultMessage):
                        result = message
            except Exception as exc:
                raise ProviderError(f"Claude query failed: {redact(str(exc))}") from exc
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        if result is None:
            raise ProviderError("Claude query returned no result")
        if result.is_error or result.subtype != "success":
            detail = redact("; ".join(result.errors or [])) or result.subtype
            raise ProviderError(f"Claude query failed: {detail}")
        usage = dict(result.usage or {})
        if result.total_cost_usd is not None:
            usage["total_cost_usd"] = result.total_cost_usd
        return CompletionResult(text=(result.result or "").strip(), usage=usage or None)
