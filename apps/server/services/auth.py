"""JWT issuing/verification, refresh tokens and FastAPI auth dependencies.

The access token is a short-lived JWT (HS256) carrying the user id, email and
role. It is delivered to the browser as an httpOnly cookie; the dependencies
below read it from that cookie (falling back to an ``Authorization: Bearer``
header for non-browser clients) and resolve the current user.

Sessions outlive the access token thanks to a long-lived refresh token: an
opaque random value, stored hashed in the ``refresh_tokens`` table and rotated
on every use (see ``rotate_refresh_token``). Reusing an already-rotated token
revokes its whole family — a replayed stolen token logs the thief *and* the
victim out instead of silently minting fresh sessions.
"""

import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from joserfc.jwt import JWTClaimsRegistry
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.database import get_db
from server.core.security import verify_password
from server.models.user import RefreshToken, User, UserRole
from server.services.users import get_user_by_email

_ALGORITHM = "HS256"
_DEV_SECRET = "dev-insecure-secret-change-me"


# The signing key and claims registry are derived from a secret that doesn't
# change within the process, so build them once instead of on every request.
# Keyed by the secret so a config change (e.g. in tests) still rebuilds the key.
@lru_cache(maxsize=None)
def _signing_key_for(secret: str) -> OctKey:
    return OctKey.import_key(secret)


_CLAIMS_REGISTRY = JWTClaimsRegistry()


def _signing_key() -> OctKey:
    return _signing_key_for(config.auth_secret_key)


def _warn_if_dev_secret() -> None:
    if config.auth_secret_key == _DEV_SECRET:
        logging.warning(
            "AUTH_SECRET_KEY is the insecure dev default — set a strong value "
            "via the AUTH_SECRET_KEY env var before deploying."
        )


def create_access_token(user: User) -> str:
    """Issue a signed JWT for ``user``."""
    _warn_if_dev_secret()
    now = int(time.time())
    claims = {
        "sub": user.id,
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + config.auth_token_ttl_seconds,
    }
    return jwt.encode({"alg": _ALGORITHM}, claims, _signing_key())


def decode_access_token(token: str) -> Optional[dict]:
    """Return the token claims if valid and unexpired, else None."""
    try:
        decoded = jwt.decode(token, _signing_key(), algorithms=[_ALGORITHM])
        # Enforce expiry (and any other registered claims).
        _CLAIMS_REGISTRY.validate(decoded.claims)
        return dict(decoded.claims)
    except (JoseError, ValueError) as exc:
        logging.debug("Rejected access token: %s", exc)
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize a stored datetime for comparison (SQLite returns them naive)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _hash_refresh_token(raw: str) -> str:
    """Refresh tokens are stored hashed so a DB leak doesn't leak live sessions."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _revoke_family(db: Session, family_id: str) -> None:
    now = _utcnow()
    db.query(RefreshToken).filter(
        RefreshToken.family_id == family_id,
        RefreshToken.revoked_at.is_(None),
    ).update({RefreshToken.revoked_at: now}, synchronize_session=False)


def issue_refresh_token(
    db: Session, user: User, family_id: Optional[str] = None
) -> str:
    """Create a refresh token for ``user`` and return its raw (unhashed) value.

    ``family_id`` is only passed by ``rotate_refresh_token`` to keep the
    successor in the same family; a fresh login starts a new family.
    """
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_refresh_token(raw),
            family_id=family_id or str(uuid.uuid4()),
            expires_at=_utcnow()
            + timedelta(seconds=config.auth_refresh_token_ttl_seconds),
        )
    )
    db.commit()
    return raw


def rotate_refresh_token(db: Session, raw: str) -> Optional[tuple[User, str]]:
    """Consume ``raw`` and return ``(user, new_raw_token)``, or None if invalid.

    The presented token is revoked whatever happens. A token that was *already*
    revoked signals replay: the whole family is revoked before rejecting.
    """
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh_token(raw))
        .first()
    )
    if not row:
        return None

    now = _utcnow()
    if row.revoked_at is not None:
        logging.warning(
            "Refresh token reuse detected for user %s — revoking family", row.user_id
        )
        _revoke_family(db, row.family_id)
        db.commit()
        return None
    if _as_utc(row.expires_at) <= now:
        row.revoked_at = now
        db.commit()
        return None

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        _revoke_family(db, row.family_id)
        db.commit()
        return None

    row.revoked_at = now
    new_raw = issue_refresh_token(db, user, family_id=row.family_id)
    return user, new_raw


def revoke_refresh_token(db: Session, raw: str) -> None:
    """Revoke the family of ``raw`` (logout). Unknown tokens are a no-op."""
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh_token(raw))
        .first()
    )
    if row:
        _revoke_family(db, row.family_id)
        db.commit()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Return the user if the email/password pair is valid and active."""
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password or ""):
        return None
    return user


def _extract_token(request: Request) -> Optional[str]:
    """Read the JWT from the auth cookie, falling back to a Bearer header."""
    token = request.cookies.get(config.auth_cookie_name)
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: resolve the authenticated user or raise 401."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _extract_token(request)
    if not token:
        raise credentials_error
    claims = decode_access_token(token)
    if not claims or not claims.get("sub"):
        raise credentials_error
    user = db.query(User).filter(User.id == claims["sub"]).first()
    if not user or not user.is_active:
        raise credentials_error
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: require the current user to be an admin (else 403)."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
