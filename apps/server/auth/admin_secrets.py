"""The admin, signed in from the deployment's secrets only (ADR 0002).

``ADMIN_USERNAME``, ``ADMIN_PASSWORD_HASH`` (argon2id) and an optional
``ADMIN_TOTP_SECRET`` are the only way in for the admin. Its ``User`` row is made
from them at startup (:func:`ensure_admin_account`): ``role=admin``,
``provider="secrets"`` and a reserved email derived from the username, its
stable key. The row never grants anything by itself — :func:`verify_admin`
checks the submitted values against the environment on every sign-in.

Its credentials are the server's own (``Credentials.from_env``, see
services/credentials.py): Settings has nothing to fill.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import struct
import time
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session

from server.core.config import _pad_base32, config
from server.models.user import (
    SECRETS_ADMIN_DOMAIN,
    AuthProvider,
    User,
    UserRole,
    secrets_admin_email,
)

logger = logging.getLogger(__name__)

# argon2-cffi's defaults: argon2id, RFC 9106's low-memory profile.
_hasher = PasswordHasher()
# Checked when the username is wrong, so a failure costs one argon2 check
# whatever was wrong: the timing says nothing about which value was.
_DECOY_HASH = _hasher.hash(secrets.token_urlsafe(32))

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
# One step either side: the clock of the admin's phone may drift.
TOTP_WINDOW = 1


def hash_password(password: str) -> str:
    """An argon2id PHC string for ``password`` (``ADMIN_PASSWORD_HASH``)."""
    return _hasher.hash(password)


def configured() -> bool:
    """Whether this deployment has a secrets admin to sign in."""
    return bool(
        config.admin_username
        and (
            config.admin_password_hash
            or (config.is_development and config.admin_password)
        )
    )


def totp_enabled() -> bool:
    return configured() and bool(config.admin_totp_secret)


def totp_code(secret: str, at: float, *, step_offset: int = 0) -> str:
    """The RFC 6238 code (SHA-1, 6 digits, 30 s) of ``secret`` at time ``at``."""
    key = base64.b32decode(_pad_base32(secret), casefold=True)
    counter = int(at // TOTP_STEP_SECONDS) + step_offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def _totp_ok(otp: Optional[str], now: float) -> bool:
    if not config.admin_totp_secret:
        return True
    submitted = (otp or "").replace(" ", "")
    if len(submitted) != TOTP_DIGITS or not submitted.isdigit():
        return False
    # Compare against every code of the window, without stopping at a match.
    matched = False
    for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        code = totp_code(config.admin_totp_secret, now, step_offset=offset)
        matched |= hmac.compare_digest(code, submitted)
    return matched


def _password_ok(password: str, username_ok: bool) -> bool:
    if config.admin_password_hash:
        try:
            matched = _hasher.verify(
                config.admin_password_hash if username_ok else _DECOY_HASH, password
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            matched = False
        return matched and username_ok
    # Development only (configured() refuses it elsewhere): the password in clear.
    matched = hmac.compare_digest(
        password.encode("utf-8"), config.admin_password.encode("utf-8")
    )
    return matched and username_ok and config.is_development


def verify_admin(
    username: str, password: str, otp: Optional[str] = None, *, now=None
) -> bool:
    """True when the three values match the deployment's secrets.

    Every check runs whatever failed before it (constant-time username
    comparison, one argon2 verification, the TOTP window), so a wrong
    username, password or code look alike.
    """
    if not configured():
        return False
    username_ok = hmac.compare_digest(
        username.strip().lower().encode("utf-8"),
        config.admin_username.lower().encode("utf-8"),
    )
    password_ok = _password_ok(password, username_ok)
    otp_ok = _totp_ok(otp, time.time() if now is None else now)
    return username_ok and password_ok and otp_ok


def ensure_admin_account(db: Session) -> Optional[User]:
    """Create or update the secrets admin's row from the environment.

    Run at startup, after the migrations, and again by the sign-in (so a
    process that skipped startup still finds it). A renamed ``ADMIN_USERNAME``
    makes a new admin; the previous secrets admin is disabled and its sessions
    end. Returns the admin, or None when the deployment has none.
    """
    from server.services import audit
    from server.services.auth import end_all_sessions

    if not configured():
        return None
    email = secrets_admin_email(config.admin_username)
    admin = db.query(User).filter(User.email == email).first()
    if admin is None:
        admin = User(
            email=email,
            hashed_password=None,
            role=UserRole.ADMIN,
            provider=AuthProvider.SECRETS,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        audit.record(db, "admin.created", target=admin, commit=False)
    elif (
        admin.role != UserRole.ADMIN
        or not admin.is_active
        or admin.provider != AuthProvider.SECRETS
    ):
        admin.role = UserRole.ADMIN
        admin.is_active = True
        admin.provider = AuthProvider.SECRETS
    db.commit()

    previous = (
        db.query(User)
        .filter(
            User.provider == AuthProvider.SECRETS,
            User.id != admin.id,
            User.is_active.is_(True),
        )
        .all()
    )
    for old in previous:
        old.is_active = False
        audit.record(
            db,
            "admin.disabled",
            target=old,
            detail={"reason": "ADMIN_USERNAME changed"},
            commit=False,
        )
        end_all_sessions(db, old)  # commits
        logger.warning("Previous secrets admin %s disabled", old.id)
    return admin


def is_secrets_admin(user: Optional[User]) -> bool:
    return bool(
        user is not None
        and user.provider == AuthProvider.SECRETS
        and (user.email or "").endswith("@" + SECRETS_ADMIN_DOMAIN)
    )


def is_current_secrets_admin(user: Optional[User]) -> bool:
    """The secrets admin of the current ``ADMIN_USERNAME`` (a renamed one's
    previous row is an ordinary, disabled account)."""
    return (
        is_secrets_admin(user)
        and configured()
        and user is not None
        and user.email == secrets_admin_email(config.admin_username)
    )
