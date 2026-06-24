"""JWT issuing/verification and FastAPI auth dependencies.

The access token is a short-lived JWT (HS256) carrying the user id, email and
role. It is delivered to the browser as an httpOnly cookie; the dependencies
below read it from that cookie (falling back to an ``Authorization: Bearer``
header for non-browser clients) and resolve the current user.
"""

import logging
import time
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
from server.models.user import User, UserRole
from server.services.users import get_user_by_email

_ALGORITHM = "HS256"
_DEV_SECRET = "dev-insecure-secret-change-me"


def _signing_key() -> OctKey:
    return OctKey.import_key(config.auth_secret_key)


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
        JWTClaimsRegistry().validate(decoded.claims)
        return dict(decoded.claims)
    except (JoseError, ValueError) as exc:
        logging.debug("Rejected access token: %s", exc)
        return None


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
