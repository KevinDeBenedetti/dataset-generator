"""Platform-wide switches, set by admins in the backoffice (``platform_settings``).

| key                     | type  | default (no row)                 |
| ----------------------- | ----- | -------------------------------- |
| ``signup_policy``        | str   | ``open`` in development, ``closed`` elsewhere: who a first sign-in may create an account for |
| ``signup_orgs``          | [str] | [] — the HF organisations of the ``orgs`` policy |
| ``signup_usernames``     | [str] | [] — HF usernames that may always sign up (invitations) |
| ``allowed_llm_hosts``    | [str] | [] — api.openai.com only         |
| ``allow_custom_base_url``| bool  | false                            |
| ``allowed_sql_hosts``    | [str] | [] — no remote database at all   |

The sign-up policy is applied once, at the first sign-in of an account
(:func:`check_signup`); existing accounts are not re-checked.

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
from server.core.i18n import DEFAULT_LOCALE, tr
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


_HF_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


def _hf_names(value: Any) -> List[str]:
    """Hugging Face account or organisation names (compared in lower case)."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("must be a list of names")
    cleaned = [v.strip().lower().lstrip("@") for v in value if v.strip()]
    bad = [v for v in cleaned if not _HF_NAME.match(v)]
    if bad:
        raise ValueError(f"not a valid Hugging Face name: {', '.join(bad)}")
    return list(dict.fromkeys(cleaned))


# Who a first sign-in may create an account for.
SIGNUP_CLOSED = "closed"
SIGNUP_ORGS = "orgs"
SIGNUP_OPEN = "open"
SIGNUP_POLICIES = (SIGNUP_CLOSED, SIGNUP_ORGS, SIGNUP_OPEN)


def _policy(value: Any) -> str:
    if value not in SIGNUP_POLICIES:
        raise ValueError(f"must be one of {', '.join(SIGNUP_POLICIES)}")
    return value


@dataclass(frozen=True)
class Switch:
    label: str
    default: Callable[[], Any]
    validate: Callable[[Any], Any]
    # The values a choice switch takes (None: a bool or a list).
    choices: Optional[tuple] = None


SWITCHES: Dict[str, Switch] = {
    "signup_policy": Switch(
        "Who can sign up: nobody new, members of the organisations below, or any "
        "Hugging Face account",
        lambda: SIGNUP_OPEN if config.allow_signup else SIGNUP_CLOSED,
        _policy,
        choices=SIGNUP_POLICIES,
    ),
    "signup_orgs": Switch(
        "Hugging Face organisations whose members may sign up (the orgs policy)",
        list,
        _hf_names,
    ),
    "signup_usernames": Switch(
        "Hugging Face usernames that may always sign up (invitations)",
        list,
        _hf_names,
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
    "allowed_sql_hosts": Switch(
        "PostgreSQL hosts a remote database data source may read (none: the connector is off)",
        list,
        _names("host"),
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


def snapshot(locale: str = DEFAULT_LOCALE) -> List[Dict[str, Any]]:
    """Every switch with its value, its label in ``locale`` (core/i18n.py)."""
    stored = _stored()
    return [
        {
            "key": key,
            "label": tr(locale, f"platform.{key}", switch.label),
            "value": stored[key] if key in stored else switch.default(),
            "overridden": key in stored,
            "choices": list(switch.choices) if switch.choices else None,
        }
        for key, switch in SWITCHES.items()
    ]


def update(
    db: Session,
    actor: User,
    changes: Dict[str, Any],
    ip: Optional[str] = None,
    locale: str = DEFAULT_LOCALE,
):
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
    before = {key: get(key) for key in validated}
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
        db,
        "platform.updated",
        actor=actor,
        ip=ip,
        detail={"changes": validated, "before": before},
    )
    clear_cache()
    return snapshot(locale)


# --- typed accessors used across the app ---------------------------------------


def signup_policy() -> str:
    value = get("signup_policy")
    return value if value in SIGNUP_POLICIES else SIGNUP_CLOSED


def allow_signup() -> bool:
    """Whether anyone at all may sign up: the login page's "a first sign-in
    creates your account" (and the SSO sign-ups', which know no organisation)."""
    return signup_policy() == SIGNUP_OPEN


def signup_possible() -> bool:
    """Whether some new account may still be created (an invitation, an org)."""
    return signup_policy() != SIGNUP_CLOSED or bool(get("signup_usernames"))


def check_signup(
    username: str, orgs: List[str], *, fine_grained: bool = False
) -> Optional[tuple[str, str]]:
    """Why a first sign-in of HF account ``username`` (member of ``orgs``, as
    its token's ``whoami`` lists them) may not create an account, as
    ``(code, message)``; None when it may."""
    if username.lower() in (get("signup_usernames") or []):
        return None
    policy = signup_policy()
    if policy == SIGNUP_OPEN:
        return None
    if policy == SIGNUP_ORGS:
        allowed = set(get("signup_orgs") or [])
        if allowed & {o.lower() for o in orgs}:
            return None
        if fine_grained and not orgs:
            return (
                "signup_orgs_hidden",
                "Your token doesn't show your organisations: give it the "
                "permission to read your organisation memberships, then retry",
            )
        return (
            "signup_not_member",
            "Sign-up is limited to members of certain organisations",
        )
    return ("signup_closed", "Sign-up is closed on this server")


def allowed_llm_hosts() -> List[str]:
    return [
        "api.openai.com",
        *[h for h in get("allowed_llm_hosts") or [] if h != "api.openai.com"],
    ]


def allowed_sql_hosts() -> List[str]:
    """The database hosts a ``sql_remote`` data source may connect to."""
    return list(get("allowed_sql_hosts") or [])


def allow_custom_base_url() -> bool:
    return bool(get("allow_custom_base_url"))
