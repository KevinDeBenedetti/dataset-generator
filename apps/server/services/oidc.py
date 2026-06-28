"""OIDC (Infomaniak) integration via Authlib's Starlette OAuth client.

Login is enabled only when the issuer and client credentials are configured.
The OAuth client is built lazily from the discovery document
(``<issuer>/.well-known/openid-configuration``) so the module imports cleanly
even when OIDC is turned off.
"""

import logging
from typing import Optional

from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.user import User, UserRole, AuthProvider
from server.services.users import get_user_by_email, get_user_by_oidc_sub

# Authlib registry name for the Infomaniak provider.
PROVIDER_NAME = "infomaniak"

_oauth: Optional[OAuth] = None


def is_oidc_configured() -> bool:
    """True when issuer + client id/secret are all set."""
    return bool(
        config.oidc_issuer and config.oidc_client_id and config.oidc_client_secret
    )


def get_oauth() -> OAuth:
    """Return a lazily-built OAuth registry with the Infomaniak provider.

    Raises RuntimeError if OIDC isn't configured — callers should gate on
    ``is_oidc_configured()`` and return a 503 first.
    """
    global _oauth
    if not is_oidc_configured():
        raise RuntimeError("OIDC is not configured")
    if _oauth is None:
        oauth = OAuth()
        oauth.register(
            name=PROVIDER_NAME,
            client_id=config.oidc_client_id,
            client_secret=config.oidc_client_secret,
            server_metadata_url=(
                config.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": config.oidc_scopes},
        )
        _oauth = oauth
    return _oauth


def reset_oauth_cache() -> None:
    """Clear the cached OAuth registry (for tests / after a config change)."""
    global _oauth
    _oauth = None


def upsert_oidc_user(
    db: Session, *, sub: str, email: str, email_verified: bool = False
) -> User:
    """Find or create the local account for an OIDC identity.

    Resolution order:
    1. Match on the OIDC subject (already-linked account).
    2. Match on a **verified** email (link an existing local account to this
       OIDC identity).
    3. Otherwise create a new OIDC account with the ``user`` role.

    The email is only trusted when the provider asserts ``email_verified``.
    Without that check, an attacker could register an unverified email matching
    an existing local account (e.g. an admin) at the IdP and take it over by
    logging in via OIDC. An unverified email is therefore ignored for both
    linking and identity: the account is created under a ``{sub}@oidc.local``
    placeholder instead.
    """
    if not sub:
        raise ValueError("OIDC userinfo is missing the 'sub' claim")

    user = get_user_by_oidc_sub(db, sub)
    if user:
        return user

    email = (email or "").lower()
    trusted_email = email if (email and email_verified) else ""

    if trusted_email:
        existing = get_user_by_email(db, trusted_email)
        if existing:
            existing.oidc_sub = sub
            if existing.provider == AuthProvider.LOCAL and not existing.hashed_password:
                existing.provider = AuthProvider.OIDC
            db.commit()
            db.refresh(existing)
            logging.info("Linked existing account %s to OIDC sub", trusted_email)
            return existing
    elif email:
        logging.warning(
            "OIDC sub=%s presented an unverified email; not linking by email", sub
        )

    user = User(
        email=trusted_email or f"{sub}@oidc.local",
        hashed_password=None,
        role=UserRole.USER,
        provider=AuthProvider.OIDC,
        oidc_sub=sub,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logging.info("Created OIDC account for sub=%s (%s)", sub, user.email)
    return user
