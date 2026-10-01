"""The credentials one request or run acts with.

A :class:`Credentials` is built once (per request, or per job run) and handed
explicitly to everything that calls a paid or private API — there is no
process-wide "current key". Two sources:

* :func:`resolve_credentials` — the signed-in user's own secrets and settings
  (services/user_secrets.py). Where ``ALLOW_ENV_CREDENTIALS`` is on (development
  only by default) a value the user hasn't entered falls back to the server's
  env var; production never falls back, so a user who added no key gets
  "not configured", never someone else's.
* :meth:`Credentials.from_env` — the server's own env, for the scheduled CI jobs.

Secrets are ``SecretStr``: they print as ``**********`` in logs, reprs and
tracebacks, and are only revealed at the call that needs them.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from pydantic import SecretStr

from server.core.config import _env, config

# Secret kinds (the ``kind`` of a ``user_secrets`` row) and what each one is.
OPENAI_API_KEY = "openai_api_key"
CLAUDE_TOKEN = "claude_token"
ANTHROPIC_API_KEY = "anthropic_api_key"
HF_TOKEN = "hf_token"
GITHUB_TOKEN = "github_token"

SECRET_KINDS = (OPENAI_API_KEY, CLAUDE_TOKEN, ANTHROPIC_API_KEY, HF_TOKEN, GITHUB_TOKEN)
# Kinds whose last four characters are safe to show ("…sk-…a1b2"). An OAuth
# token's tail says as much about the account as its head, so those get none.
HINT_KINDS = (OPENAI_API_KEY, ANTHROPIC_API_KEY, HF_TOKEN, GITHUB_TOKEN)

# Non-secret settings a user can save, and the env var each falls back to.
SETTING_ENV = {
    "openai_base_url": "OPENAI_BASE_URL",
    "hf_namespace": "HF_NAMESPACE",
    "hf_qa_repo": "HF_QA_DATASET_REPO",
    "hf_corpus_repo": "HF_DATASET_REPO",
    "github_username": "GITHUB_USERNAME",
}
_SECRET_ENV = {
    OPENAI_API_KEY: "OPENAI_API_KEY",
    CLAUDE_TOKEN: "CLAUDE_CODE_OAUTH_TOKEN",
    ANTHROPIC_API_KEY: "ANTHROPIC_API_KEY",
    HF_TOKEN: "HF_TOKEN",
    GITHUB_TOKEN: "GITHUB_TOKEN",
}


def _secret(value: Optional[str]) -> Optional[SecretStr]:
    value = (value or "").strip()
    return SecretStr(value) if value else None


@dataclass(frozen=True)
class Credentials:
    openai_api_key: Optional[SecretStr] = None
    claude_token: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None
    hf_token: Optional[SecretStr] = None
    github_token: Optional[SecretStr] = None
    openai_base_url: str = ""
    hf_namespace: str = ""
    hf_qa_repo: str = ""
    hf_corpus_repo: str = ""
    github_username: str = ""
    # True when ``openai_base_url`` comes from the operator's own env (it may be a
    # private gateway); a URL a user typed is never trusted (core/net.py applies).
    base_url_trusted: bool = False

    def secret(self, kind: str) -> str:
        """The plaintext of a secret ('' when unset). Call it at the point of use."""
        value: Optional[SecretStr] = getattr(self, kind)
        return value.get_secret_value() if value else ""

    def has(self, kind: str) -> bool:
        return bool(self.secret(kind))

    @classmethod
    def from_env(cls) -> "Credentials":
        """The server's own env — scheduled jobs and the development fallback."""
        settings = {key: _env(name).strip() for key, name in SETTING_ENV.items()}
        secrets: Dict[str, Any] = {
            kind: _secret(_env(name)) for kind, name in _SECRET_ENV.items()
        }
        return cls(
            **secrets,
            **settings,
            base_url_trusted=bool(settings["openai_base_url"]),
        )

    def filled_from(self, fallback: "Credentials") -> "Credentials":
        """Self, with every value it lacks taken from ``fallback``."""
        updates: Dict[str, object] = {}
        for kind in SECRET_KINDS:
            if not self.has(kind) and fallback.has(kind):
                updates[kind] = getattr(fallback, kind)
        for key in SETTING_ENV:
            if not getattr(self, key) and getattr(fallback, key):
                updates[key] = getattr(fallback, key)
        if "openai_base_url" in updates and fallback.base_url_trusted:
            updates["base_url_trusted"] = True
        return replace(self, **updates) if updates else self

    def __repr__(self) -> str:  # never print values, not even masked lengths
        configured = [k for k in SECRET_KINDS if self.has(k)]
        return f"Credentials(configured={configured})"


def resolve_credentials(user_id: str) -> Credentials:
    """``user_id``'s own credentials (plus the env fallback where it is allowed)."""
    from server.services.user_secrets import load_credentials

    creds = load_credentials(user_id)
    if config.allow_env_credentials:
        creds = creds.filled_from(Credentials.from_env())
    return creds


def env_credentials() -> Credentials:
    """The credentials of an actor with no account: the CI cron entrypoints."""
    return Credentials.from_env()
