"""The credentials one request or run acts with.

A :class:`Credentials` is built once (per request, or per job run) and handed
explicitly to everything that calls a paid or private API — there is no
process-wide "current key". Two sources:

* :func:`resolve_credentials` — the signed-in user's own secrets and settings
  (services/user_secrets.py). In development only, a value the user hasn't
  entered falls back to the server's env var. Production falls back for one
  thing only: with ``SERVER_LLM_FOR_ADMINS``, an admin who saved no
  OpenAI-compatible key calls the server's endpoint with the server's key. Any
  other user who added no key gets "not configured", never someone else's.
* :meth:`Credentials.from_env` — the server's own env, the development fallback.

The OpenAI-compatible key and its endpoint always travel as a pair: the
server's key never goes to a URL a user typed, nor a user's key to the
server's URL.

Secrets are ``SecretStr``: they print as ``**********`` in logs, reprs and
tracebacks, and are only revealed at the call that needs them.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from pydantic import SecretStr

from server.core.config import _env, config

# Secret kinds (the ``kind`` of a ``user_secrets`` row) and what each one is.
OPENAI_API_KEY = "openai_api_key"
HF_TOKEN = "hf_token"  # noqa: S105 — a kind's name, not a value
GITHUB_TOKEN = "github_token"  # noqa: S105 — a kind's name, not a value

SECRET_KINDS = (OPENAI_API_KEY, HF_TOKEN, GITHUB_TOKEN)
# Kinds whose last four characters are safe to show ("…sk-…a1b2"). An OAuth
# token's tail says as much about the account as its head, so those get none.
HINT_KINDS = (OPENAI_API_KEY, HF_TOKEN, GITHUB_TOKEN)

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
    HF_TOKEN: "HF_TOKEN",
    GITHUB_TOKEN: "GITHUB_TOKEN",
}


def _secret(value: Optional[str]) -> Optional[SecretStr]:
    value = (value or "").strip()
    return SecretStr(value) if value else None


@dataclass(frozen=True)
class Credentials:
    openai_api_key: Optional[SecretStr] = None
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
    # True when the OpenAI-compatible key and endpoint are the server's, lent
    # to this user (see :func:`resolve_credentials`).
    openai_from_server: bool = False
    # Whose they are ('' for the env's or a test's): what the checks read the
    # user's embedding model and its thresholds by (services/semantic.py).
    user_id: str = ""

    def secret(self, kind: str) -> str:
        """The plaintext of a secret ('' when unset). Call it at the point of use."""
        value: Optional[SecretStr] = getattr(self, kind)
        return value.get_secret_value() if value else ""

    def has(self, kind: str) -> bool:
        return bool(self.secret(kind))

    @classmethod
    def from_env(cls) -> "Credentials":
        """The server's own env — the development fallback."""
        settings = {key: _env(name).strip() for key, name in SETTING_ENV.items()}
        secrets: Dict[str, Any] = {
            kind: _secret(_env(name)) for kind, name in _SECRET_ENV.items()
        }
        return cls(
            **secrets,
            **settings,
            base_url_trusted=bool(settings["openai_base_url"]),
        )

    def with_openai_of(self, other: "Credentials") -> "Credentials":
        """Self, calling ``other``'s OpenAI-compatible endpoint with ``other``'s key.

        The key and its endpoint are taken together, never one without the
        other; self unchanged when ``other`` has no key."""
        if not other.has(OPENAI_API_KEY):
            return self
        return replace(
            self,
            openai_api_key=other.openai_api_key,
            openai_base_url=other.openai_base_url,
            base_url_trusted=other.base_url_trusted,
            openai_from_server=True,
        )

    def filled_from(self, fallback: "Credentials") -> "Credentials":
        """Self, with every value it lacks taken from ``fallback`` — except the
        OpenAI-compatible endpoint, which only comes with ``fallback``'s key:
        self's own key keeps self's endpoint (OpenAI's when blank)."""
        updates: Dict[str, object] = {}
        for kind in SECRET_KINDS:
            if kind == OPENAI_API_KEY:
                continue
            if not self.has(kind) and fallback.has(kind):
                updates[kind] = getattr(fallback, kind)
        for key in SETTING_ENV:
            if key == "openai_base_url":
                continue
            if not getattr(self, key) and getattr(fallback, key):
                updates[key] = getattr(fallback, key)
        filled = replace(self, **updates) if updates else self
        return filled if self.has(OPENAI_API_KEY) else filled.with_openai_of(fallback)

    def __repr__(self) -> str:  # never print values, not even masked lengths
        configured = [k for k in SECRET_KINDS if self.has(k)]
        return f"Credentials(configured={configured})"


def resolve_credentials(user_id: str, is_admin: Optional[bool] = None) -> Credentials:
    """``user_id``'s own credentials, plus what the server lends them.

    In development, every value the user hasn't entered comes from the env.
    Elsewhere, only an admin (``is_admin``, looked up when not given) without
    an OpenAI-compatible key of their own gets the server's, with its endpoint,
    and only when ``SERVER_LLM_FOR_ADMINS`` is on. The role is read at each
    resolution, so a demoted admin loses it at their next request or run.
    """
    from server.services.user_secrets import load_credentials, user_is_admin

    creds = load_credentials(user_id)
    if config.allow_env_credentials:
        creds = creds.filled_from(Credentials.from_env())
    elif config.server_llm_for_admins and not creds.has(OPENAI_API_KEY):
        if user_is_admin(user_id) if is_admin is None else is_admin:
            creds = creds.with_openai_of(Credentials.from_env())
    return replace(creds, user_id=user_id)
