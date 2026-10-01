"""Storing a user's secrets (encrypted) and settings.

Secrets are write-only: nothing here returns a plaintext to the API. Reading a
plaintext happens only in :func:`load_credentials`, which builds the
:class:`~server.services.credentials.Credentials` a request or run acts with.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.crypto import CryptoError, SecretBox, aad_for, build_box
from server.core.database import get_scoped_db
from server.models.user_secret import UserSecret, UserSettings
from server.services.credentials import (
    HINT_KINDS,
    SECRET_KINDS,
    SETTING_ENV,
    Credentials,
    _secret,
)

logger = logging.getLogger(__name__)

MAX_SECRET_LENGTH = 4096
MAX_SETTING_LENGTH = 300


class SecretError(ValueError):
    """A secret or setting is invalid; the message is safe to show."""


def get_box() -> SecretBox:
    """The key ring in force (derived from AUTH_SECRET_KEY in development only)."""
    return build_box(
        config.secrets_encryption_keys_raw,
        config.auth_secret_key if config.is_development else "",
    )


def _hint(kind: str, value: str) -> Optional[str]:
    return value[-4:] if kind in HINT_KINDS and len(value) >= 12 else None


def set_secret(user_id: str, kind: str, value: str) -> Dict[str, Any]:
    """Store (or replace) ``user_id``'s secret of ``kind``. Returns its status."""
    if kind not in SECRET_KINDS:
        raise SecretError(f"Unknown secret '{kind}'")
    value = (value or "").strip()
    if not value:
        raise SecretError("The value is empty")
    if len(value) > MAX_SECRET_LENGTH or any(c.isspace() for c in value):
        raise SecretError("That does not look like a valid key or token")
    ciphertext, key_id = get_box().encrypt(value, aad_for(user_id, kind))
    with get_scoped_db() as db:
        row = db.get(UserSecret, {"user_id": user_id, "kind": kind})
        if row is None:
            row = UserSecret(user_id=user_id, kind=kind)
            db.add(row)
        row.ciphertext, row.key_id = ciphertext, key_id
        row.hint = _hint(kind, value)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _status(row)


def delete_secret(user_id: str, kind: str) -> bool:
    if kind not in SECRET_KINDS:
        raise SecretError(f"Unknown secret '{kind}'")
    with get_scoped_db() as db:
        row = db.get(UserSecret, {"user_id": user_id, "kind": kind})
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True


def _status(row: UserSecret) -> Dict[str, Any]:
    return {
        "kind": row.kind,
        "configured": True,
        "hint": row.hint,
        "updated_at": row.updated_at,
    }


def secret_statuses(user_id: str) -> Dict[str, Dict[str, Any]]:
    """``{kind: {configured, hint, updated_at}}`` for every kind — no plaintext."""
    out: Dict[str, Dict[str, Any]] = {
        kind: {"kind": kind, "configured": False, "hint": None, "updated_at": None}
        for kind in SECRET_KINDS
    }
    with get_scoped_db() as db:
        for row in db.scalars(select(UserSecret).where(UserSecret.user_id == user_id)):
            if row.kind in out:
                out[row.kind] = _status(row)
    return out


def get_settings(user_id: str) -> Dict[str, str]:
    with get_scoped_db() as db:
        row = db.get(UserSettings, user_id)
        stored = dict(row.data) if row is not None else {}
    return {key: str(stored.get(key, "")) for key in SETTING_ENV}


def update_settings(user_id: str, changes: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Merge ``changes`` (``None``/blank clears a key). Unknown keys are refused."""
    unknown = set(changes) - set(SETTING_ENV)
    if unknown:
        raise SecretError(f"Unknown setting: {', '.join(sorted(unknown))}")
    cleaned: Dict[str, str] = {}
    for key, value in changes.items():
        text = (value or "").strip()
        if len(text) > MAX_SETTING_LENGTH:
            raise SecretError(f"'{key}' is too long")
        cleaned[key] = text
    with get_scoped_db() as db:
        row = db.get(UserSettings, user_id)
        if row is None:
            row = UserSettings(user_id=user_id, data={})
            db.add(row)
        merged = {**(row.data or {}), **cleaned}
        row.data = {k: v for k, v in merged.items() if v}
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    return get_settings(user_id)


def load_credentials(user_id: str) -> Credentials:
    """The user's stored credentials. A secret that fails to decrypt counts as unset
    (logged, without the value): one unreadable row must not take the app down."""
    box = get_box()
    secrets: Dict[str, Any] = {}
    with get_scoped_db() as db:
        for row in db.scalars(select(UserSecret).where(UserSecret.user_id == user_id)):
            if row.kind not in SECRET_KINDS:
                continue
            try:
                plain = box.decrypt(
                    row.ciphertext, row.key_id, aad_for(row.user_id, row.kind)
                )
            except CryptoError as exc:
                logger.error(
                    "Secret %s of user %s unreadable: %s", row.kind, user_id, exc
                )
                continue
            secrets[row.kind] = _secret(plain)
    return Credentials(**secrets, **get_settings(user_id))


def rewrap_all(db: Session, box: Optional[SecretBox] = None) -> Dict[str, int]:
    """Re-encrypt every secret under the primary key (after a ring rotation)."""
    box = box or get_box()
    counts = {"rewrapped": 0, "unchanged": 0, "failed": 0}
    for row in db.scalars(select(UserSecret)):
        aad = aad_for(row.user_id, row.kind)
        if row.key_id == box.primary_id:
            counts["unchanged"] += 1
            continue
        try:
            plain = box.decrypt(row.ciphertext, row.key_id, aad)
        except CryptoError:
            counts["failed"] += 1
            continue
        row.ciphertext, row.key_id = box.encrypt(plain, aad)
        counts["rewrapped"] += 1
    db.commit()
    return counts
