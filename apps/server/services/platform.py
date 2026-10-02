"""Platform-wide switches, set by admins in the backoffice (``platform_settings``).

| key                     | type  | default (no row)                 |
| ----------------------- | ----- | -------------------------------- |
| ``allow_signup``         | bool  | true — a first SSO sign-in creates an account |
| ``allowed_email_domains``| [str] | [] — any domain                  |
| ``allowed_llm_hosts``    | [str] | [] — api.openai.com only         |
| ``allow_custom_base_url``| bool  | false                            |

Values are cached for a few seconds per process (they are read on every model
call); a change made on one replica reaches the others within that delay.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.core.config import config
from server.core.database import get_scoped_db
from server.models.platform_settings import PlatformSetting
from server.models.user import User
from server.services import audit

logger = logging.getLogger(__name__)

CACHE_TTL_S = 15.0
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _names(kind: str) -> Callable[[Any], List[str]]:
    def check(value: Any) -> List[str]:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("must be a list of names")
        cleaned = [
            v.strip().lower().lstrip("@").rstrip(".") for v in value if v.strip()
        ]
        bad = [v for v in cleaned if not _HOST.match(v)]
        if bad:
            raise ValueError(f"not a valid {kind}: {', '.join(bad)}")
        return list(dict.fromkeys(cleaned))

    return check


@dataclass(frozen=True)
class Switch:
    label: str
    default: Callable[[], Any]
    validate: Callable[[Any], Any]


SWITCHES: Dict[str, Switch] = {
    "allow_signup": Switch(
        "A first sign-in creates an account", lambda: config.allow_signup, _bool
    ),
    "allowed_email_domains": Switch(
        "Sign-ups limited to these email domains (empty: any)",
        lambda: config.allowed_email_domains,
        _names("domain"),
    ),
    "allowed_llm_hosts": Switch(
        "Extra hosts a user's OpenAI-compatible base URL may use (besides api.openai.com)",
        lambda: [h for h in config.allowed_llm_hosts if h != "api.openai.com"],
        _names("host"),
    ),
    "allow_custom_base_url": Switch(
        "Users may point at any public https endpoint",
        lambda: config.allow_custom_base_url,
        _bool,
    ),
}

_cache: Optional[tuple[float, Dict[str, Any]]] = None


def clear_cache() -> None:
    global _cache
    _cache = None


def _stored() -> Dict[str, Any]:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_TTL_S:
        return _cache[1]
    values: Dict[str, Any] = {}
    try:
        with get_scoped_db() as db:
            for row in db.scalars(select(PlatformSetting)):
                if row.key in SWITCHES:
                    values[row.key] = row.value
    except Exception as exc:  # noqa: BLE001 — a DB blip must not break model calls
        logger.warning("Could not read platform settings, using the defaults: %s", exc)
        return {}
    _cache = (now, values)
    return values


def get(key: str) -> Any:
    stored = _stored()
    return stored[key] if key in stored else SWITCHES[key].default()


def snapshot() -> List[Dict[str, Any]]:
    stored = _stored()
    return [
        {
            "key": key,
            "label": switch.label,
            "value": stored[key] if key in stored else switch.default(),
            "overridden": key in stored,
        }
        for key, switch in SWITCHES.items()
    ]


def update(db: Session, actor: User, changes: Dict[str, Any], ip: Optional[str] = None):
    """Validate then store ``changes``; ``None`` resets a switch to its default.
    ValueError names the first invalid one."""
    validated: Dict[str, Any] = {}
    for key, value in changes.items():
        if key not in SWITCHES:
            raise ValueError(f"Unknown setting '{key}'")
        try:
            validated[key] = None if value is None else SWITCHES[key].validate(value)
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from None
    for key, value in validated.items():
        row = db.get(PlatformSetting, key)
        if value is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            row = PlatformSetting(key=key)
            db.add(row)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = actor.id
    audit.record(
        db, "platform.updated", actor=actor, ip=ip, detail={"changes": validated}
    )
    clear_cache()
    return snapshot()


# --- typed accessors used across the app ---------------------------------------


def allow_signup() -> bool:
    return bool(get("allow_signup"))


def allowed_email_domains() -> List[str]:
    return list(get("allowed_email_domains") or [])


def allowed_llm_hosts() -> List[str]:
    return [
        "api.openai.com",
        *[h for h in get("allowed_llm_hosts") or [] if h != "api.openai.com"],
    ]


def allow_custom_base_url() -> bool:
    return bool(get("allow_custom_base_url"))
