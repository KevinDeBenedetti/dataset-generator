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

from server.core.config import DEV_AUTH_SECRET, config
from server.core.database import get_db
from server.core.security import verify_password
from server.models.user import RefreshToken, User, UserRole
from server.services.users import get_user_by_email

_ALGORITHM = "HS256"


# The signing key and claims registry are derived from a secret that doesn't
# change within the process, so build them once instead of on every request.
# Keyed by the secret so a config change (e.g. in tests) still rebuilds the key.
@lru_cache(maxsize=None)
def _signing_key_for(secret: str) -> OctKey:
    return OctKey.import_key(secret)


def _claims_registry() -> JWTClaimsRegistry:
    """Expiry plus issuer and audience: a token minted for another service that
    happens to share the secret must not be accepted here."""
    return JWTClaimsRegistry(
        iss={"essential": True, "value": config.auth_issuer},
        aud={"essential": True, "value": config.auth_audience},
    )


def _signing_key() -> OctKey:
    return _signing_key_for(config.auth_secret_key)


def ensure_secret_is_safe() -> None:
    """Refuse the public dev secret outside development.

    Anyone holding it can forge access tokens and the OIDC session cookie, so a
    deployment that forgot AUTH_SECRET_KEY must not start at all.
    """
    if config.auth_secret_key == DEV_AUTH_SECRET and not config.is_development:
        raise RuntimeError(
            "AUTH_SECRET_KEY is the public dev default. Set it to a long random "
            "value, or set ENVIRONMENT=development for local dev."
        )


def _warn_if_dev_secret() -> None:
    if config.auth_secret_key == DEV_AUTH_SECRET:
        logging.warning(
            "AUTH_SECRET_KEY is the insecure dev default — set a strong value "
            "via the AUTH_SECRET_KEY env var before deploying."
        )


def create_access_token(user: User) -> str:
    """Issue a signed JWT for ``user``."""
    _warn_if_dev_secret()
    now = int(time.time())
    claims = {
        "iss": config.auth_issuer,
        "aud": config.auth_audience,
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
        # Enforce expiry, issuer and audience.
        _claims_registry().validate(decoded.claims)
        return dict(decoded.claims)
    except (JoseError, ValueError) as exc:
        logging.debug("Rejected access token: %s", exc)
        return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalize a stored datetime for comparison.

    The columns are ``TIMESTAMP WITHOUT TIME ZONE``, so Postgres hands back
    naive datetimes; the values are written as UTC, so that is what we assume.
    """
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

    Rotation is atomic: the token is claimed with a conditional
    ``UPDATE … WHERE revoked_at IS NULL``, so of two concurrent requests
    presenting it exactly one wins the claim — a read-then-write would let both
    mint a session. The loser is then either a harmless race (the token was
    rotated within ``auth_refresh_reuse_grace_seconds``: it gets its own
    successor in the same family) or replay, which revokes the whole family.
    """
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_refresh_token(raw))
        .first()
    )
    if not row:
        return None

    now = _utcnow()
    if _as_utc(row.expires_at) <= now:
        row.revoked_at = row.revoked_at or now
        db.commit()
        return None

    claimed = (
        db.query(RefreshToken)
        .filter(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    if not claimed:
        # Someone consumed it between our read and our write (or earlier).
        db.expire(row)
        db.refresh(row)
        grace = timedelta(seconds=config.auth_refresh_reuse_grace_seconds)
        # "Just rotated" needs a live successor in the family: after a logout or
        # a replay revocation every token of the family is revoked, and a token
        # revoked that way must never be forgiven.
        just_rotated = (
            row.revoked_at is not None
            and now - _as_utc(row.revoked_at) <= grace
            and db.query(RefreshToken)
            .filter(
                RefreshToken.family_id == row.family_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .first()
            is not None
        )
        if not just_rotated:
            logging.warning(
                "Refresh token reuse detected for user %s — revoking family",
                row.user_id,
            )
            _revoke_family(db, row.family_id)
            db.commit()
            return None

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        _revoke_family(db, row.family_id)
        db.commit()
        return None

    # issue_refresh_token commits, which also commits the claim above.
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


def end_all_sessions(db: Session, user: User) -> int:
    """Sign ``user`` out everywhere: revoke every refresh token and refuse every
    access token issued until now. Returns the number of tokens revoked."""
    now = _utcnow()
    revoked = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
    user.sessions_valid_after = now
    db.commit()
    return revoked


def _issued_before_cutoff(claims: dict, user: User) -> bool:
    """True when the token predates the user's last "sign out everywhere"."""
    if user.sessions_valid_after is None:
        return False
    cutoff = int(_as_utc(user.sessions_valid_after).timestamp())
    return int(claims.get("iat", 0)) < cutoff


def purge_expired_refresh_tokens(db: Session) -> int:
    """Delete revoked/expired refresh token rows. Returns the number removed.

    Nothing else ever deletes a row (rotation/logout/replay only set
    ``revoked_at``), so the table grows without bound otherwise. Run at
    startup (see ``main.py``'s lifespan) — cheap enough not to need a
    separate cron given the low volume.
    """
    deleted = (
        db.query(RefreshToken)
        .filter(
            (RefreshToken.revoked_at.is_not(None))
            | (RefreshToken.expires_at < _utcnow())
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


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
    if not user or not user.is_active or _issued_before_cutoff(claims, user):
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
