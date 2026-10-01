"""Live checks of a key or token before it is stored (and on demand afterwards).

Each check calls a fixed provider endpoint (api.openai.com or the user's vetted
base URL through the SSRF guard, huggingface.co, api.github.com,
api.anthropic.com) with the candidate secret, so a typo or a revoked key is
caught at save time instead of in the middle of a run. Messages never include
the secret or the provider's raw response.
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import Any

import httpx
from pydantic import SecretStr

from server.services.providers.openai import OpenAIProvider
from server.services.credentials import (
    ANTHROPIC_API_KEY,
    CLAUDE_TOKEN,
    GITHUB_TOKEN,
    HF_TOKEN,
    OPENAI_API_KEY,
    Credentials,
)

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class Check:
    ok: bool
    checked: bool
    message: str


async def _openai(creds: Credentials) -> Check:
    try:
        client = OpenAIProvider().build_client(creds)
        async with client:
            await asyncio.wait_for(client.models.list(), timeout=_TIMEOUT_S)
    except ValueError as exc:  # the base URL is not acceptable
        return Check(False, True, str(exc))
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            return Check(False, True, "OpenAI rejected this key")
        logger.warning("OpenAI key check failed: %s", type(exc).__name__)
        return Check(
            False, True, "Could not reach the OpenAI endpoint to check the key"
        )
    return Check(True, True, "The key works")


def _hf_whoami(token: str) -> dict:
    from huggingface_hub import HfApi

    return HfApi(token=token).whoami()


async def _huggingface(creds: Credentials) -> Check:
    try:
        who = await asyncio.wait_for(
            asyncio.to_thread(_hf_whoami, creds.secret(HF_TOKEN)), _TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hugging Face token check failed: %s", type(exc).__name__)
        return Check(False, True, "Hugging Face rejected this token")
    access: Any = (who.get("auth") or {}).get("accessToken") or {}
    if access.get("role") == "read":
        return Check(
            False, True, "This is a read-only token — publishing needs a write token"
        )
    namespace = creds.hf_namespace
    if namespace:
        owned = {who.get("name")} | {o.get("name") for o in who.get("orgs") or []}
        if namespace not in owned:
            return Check(
                False,
                True,
                f"This token's account is not a member of '{namespace}'",
            )
    return Check(True, True, f"Signed in as {who.get('name', 'your account')}")


async def _github(creds: Credentials) -> Check:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, trust_env=False) as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {creds.secret(GITHUB_TOKEN)}",
                    "Accept": "application/vnd.github+json",
                },
            )
    except httpx.HTTPError:
        return Check(False, True, "Could not reach GitHub to check the token")
    if response.status_code == 200:
        return Check(True, True, "The token works")
    if response.status_code in (401, 403):
        return Check(False, True, "GitHub rejected this token")
    return Check(False, True, f"GitHub answered HTTP {response.status_code}")


async def _anthropic(creds: Credentials) -> Check:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, trust_env=False) as client:
            response = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": creds.secret(ANTHROPIC_API_KEY),
                    "anthropic-version": "2023-06-01",
                },
            )
    except httpx.HTTPError:
        return Check(False, True, "Could not reach Anthropic to check the key")
    if response.status_code == 200:
        return Check(True, True, "The key works")
    if response.status_code in (401, 403):
        return Check(False, True, "Anthropic rejected this key")
    return Check(False, True, f"Anthropic answered HTTP {response.status_code}")


async def _claude_token(creds: Credentials) -> Check:
    # A subscription token can only be exercised by running the Claude CLI, which
    # spends usage — so it is checked for shape only.
    token = creds.secret(CLAUDE_TOKEN)
    if not token.startswith("sk-ant-"):
        return Check(
            False,
            True,
            "That does not look like a Claude token (run `claude setup-token`)",
        )
    return Check(True, False, "Saved — it is verified the first time a model runs")


_CHECKS = {
    OPENAI_API_KEY: _openai,
    HF_TOKEN: _huggingface,
    GITHUB_TOKEN: _github,
    ANTHROPIC_API_KEY: _anthropic,
    CLAUDE_TOKEN: _claude_token,
}


async def check_secret(kind: str, value: str, settings: Credentials) -> Check:
    """Check ``value`` as a ``kind`` secret, in the context of the user's settings."""
    candidate = replace(
        settings,
        **{kind: SecretStr(value)},
        base_url_trusted=False,  # a user-typed endpoint is never trusted
    )
    return await _CHECKS[kind](candidate)
