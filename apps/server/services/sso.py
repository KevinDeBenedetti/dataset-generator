"""Single sign-on providers: Infomaniak (OpenID Connect) and GitHub (OAuth 2).

Each provider is an Authlib Starlette client, registered lazily (the module
imports cleanly with SSO off) with PKCE (``S256``). A provider turns the token
it receives at the callback into an :class:`ExternalIdentity`; what happens next
(link, sign-up, refusal) is decided by ``services/identities.py``.

* **Infomaniak** — OIDC discovery; Authlib checks the ID token, its nonce and
  the state. ``sub`` is the subject; the email counts only with
  ``email_verified``.
* **GitHub** — plain OAuth 2 (no ID token): the subject is the numeric user id
  from ``/user`` (never the login, which can be renamed and re-registered), and
  the email is the **primary and verified** one from ``/user/emails``.
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from authlib.integrations.starlette_client import OAuth

from server.core.config import config

logger = logging.getLogger(__name__)


class SsoError(Exception):
    """The provider's answer can't be used; ``code`` is shown to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    username: Optional[str] = None


def _truthy(value: object) -> bool:
    """``email_verified`` is a JSON boolean per spec; some providers send "true"."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1")


async def _infomaniak_identity(client: Any, token: Dict[str, Any]) -> ExternalIdentity:
    info = token.get("userinfo") or {}
    sub = str(info.get("sub") or "").strip()
    if not sub:
        raise SsoError("no_subject", "The provider did not identify the account")
    return ExternalIdentity(
        provider="infomaniak",
        subject=sub,
        email=str(info.get("email") or "").strip().lower(),
        email_verified=_truthy(info.get("email_verified")),
        username=info.get("preferred_username") or info.get("name"),
    )


async def _github_identity(client: Any, token: Dict[str, Any]) -> ExternalIdentity:
    user = (await client.get("user", token=token)).json()
    subject = str(user.get("id") or "").strip()
    if not subject:
        raise SsoError("no_subject", "GitHub did not identify the account")
    emails: List[Dict[str, Any]] = (await client.get("user/emails", token=token)).json()
    primary = next(
        (e for e in emails if isinstance(e, dict) and e.get("primary")), None
    )
    verified = bool(primary and primary.get("verified"))
    return ExternalIdentity(
        provider="github",
        subject=subject,
        email=str(primary.get("email") or "").strip().lower() if primary else "",
        email_verified=verified,
        username=user.get("login"),
    )


@dataclass(frozen=True)
class SsoProvider:
    name: str
    label: str
    configured: Callable[[], bool]
    redirect_uri: Callable[[], str]
    register: Callable[[OAuth], None]
    identity: Callable[[Any, Dict[str, Any]], Awaitable[ExternalIdentity]]


def _register_infomaniak(oauth: OAuth) -> None:
    oauth.register(
        name="infomaniak",
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret,
        server_metadata_url=(
            config.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": config.oidc_scopes, "code_challenge_method": "S256"},
    )


def _register_github(oauth: OAuth) -> None:
    oauth.register(
        name="github",
        client_id=config.github_client_id,
        client_secret=config.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={
            "scope": "read:user user:email",
            "code_challenge_method": "S256",
        },
    )


PROVIDERS: Dict[str, SsoProvider] = {
    "infomaniak": SsoProvider(
        name="infomaniak",
        label="Infomaniak",
        configured=lambda: bool(
            config.oidc_issuer and config.oidc_client_id and config.oidc_client_secret
        ),
        redirect_uri=lambda: config.oidc_redirect_uri,
        register=_register_infomaniak,
        identity=_infomaniak_identity,
    ),
    "github": SsoProvider(
        name="github",
        label="GitHub",
        configured=lambda: bool(
            config.github_client_id and config.github_client_secret
        ),
        redirect_uri=lambda: config.github_redirect_uri,
        register=_register_github,
        identity=_github_identity,
    ),
}

_oauth: Optional[OAuth] = None


def get_provider(name: str) -> Optional[SsoProvider]:
    return PROVIDERS.get(name)


def get_client(provider: SsoProvider) -> Any:
    """The Authlib client for ``provider`` (registered on first use)."""
    global _oauth
    if _oauth is None:
        _oauth = OAuth()
    if provider.name not in _oauth._registry:  # noqa: SLF001 — Authlib has no has()
        provider.register(_oauth)
    return _oauth.create_client(provider.name)


def reset_oauth_cache() -> None:
    """Forget registered clients (tests, or after a configuration change)."""
    global _oauth
    _oauth = None


def list_providers() -> List[Dict[str, Any]]:
    return [
        {"name": p.name, "label": p.label, "configured": p.configured()}
        for p in PROVIDERS.values()
    ]
