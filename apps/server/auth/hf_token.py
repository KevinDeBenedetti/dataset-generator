"""Users sign in with their Hugging Face username and token (ADR 0002).

The token proves who the user is *and* lets the app publish for them, so it is
checked with the Hub's ``whoami`` at every sign-in and kept, encrypted, as the
user's ``hf_token`` secret for the worker. The account is keyed on the Hub's
stable account id (``whoami()["id"]``), never the username, which can change.

A refusal is a :class:`SignInRefused` with a code the login page translates;
the token is never logged nor echoed in a message.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from server.models.user import AuthProvider, User, UserRole
from server.services import audit

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "hf_"  # noqa: S105 — a prefix, not a value
TOKEN_MIN_CHARS = 20
TOKEN_MAX_CHARS = 200


class SignInRefused(Exception):
    """The sign-in can't proceed. ``code`` names the reason for the login page;
    ``status`` is the HTTP status the route answers."""

    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class HubUnavailable(Exception):
    """The Hub didn't answer (network error, 5xx, timeout): nobody is refused."""


@dataclass(frozen=True)
class TokenInfo:
    """What a ``whoami`` answer says about a token, the parts the app uses."""

    hf_id: str
    username: str
    email: Optional[str]
    email_verified: bool
    avatar_url: Optional[str]
    orgs: List[str]
    role: str  # "read", "write" or "fineGrained"
    can_write: bool
    # The orgs a fine-grained token can't write to (a warning, not a refusal).
    orgs_without_write: List[str]


def _fetch_whoami(token: str) -> Dict[str, Any]:
    """``whoami`` on the Hub. 401 → :class:`SignInRefused`, else
    :class:`HubUnavailable` for anything the Hub didn't answer."""
    import httpx
    from huggingface_hub import HfApi
    from huggingface_hub.errors import HfHubHTTPError

    try:
        return HfApi(token=token).whoami()
    except HfHubHTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise SignInRefused(
                "token_invalid", "Hugging Face rejected this token"
            ) from None
        raise HubUnavailable() from None
    except (httpx.HTTPError, OSError):
        raise HubUnavailable() from None


# The Hub call, replaced in tests by recorded answers (tests/fixtures/hf_whoami).
whoami_fetcher: Callable[[str], Dict[str, Any]] = _fetch_whoami


def check_token_shape(token: str) -> None:
    """Refuse what is obviously not a Hugging Face token, before any Hub call."""
    if (
        not token.startswith(TOKEN_PREFIX)
        or not TOKEN_MIN_CHARS <= len(token) <= TOKEN_MAX_CHARS
        or any(c.isspace() for c in token)
    ):
        raise SignInRefused(
            "token_malformed", "This doesn't look like a Hugging Face token"
        )


def _scoped_writes(access: Dict[str, Any]) -> Dict[str, bool]:
    """For a fine-grained token: whether it may write repos, per entity name."""
    fine = access.get("fineGrained") or {}
    writes: Dict[str, bool] = {}
    for scope in fine.get("scoped") or []:
        entity = scope.get("entity") or {}
        name = entity.get("name")
        if name:
            writes[name] = "repo.write" in (scope.get("permissions") or [])
    return writes


def token_info(who: Dict[str, Any]) -> TokenInfo:
    """Read a ``whoami`` answer (the shapes are in tests/fixtures/hf_whoami)."""
    access = (who.get("auth") or {}).get("accessToken") or {}
    role = access.get("role") or ""
    username = who.get("name") or ""
    orgs = [o.get("name") for o in who.get("orgs") or [] if o.get("name")]
    if role == "fineGrained":
        writes = _scoped_writes(access)
        global_perms = (access.get("fineGrained") or {}).get("global") or []
        can_write = writes.get(username, False) or "repo.write" in global_perms
        without = [o for o in orgs if not writes.get(o, False)]
    else:
        can_write = role == "write"
        without = [] if can_write else orgs
    return TokenInfo(
        hf_id=str(who.get("id") or ""),
        username=username,
        email=who.get("email") or None,
        email_verified=bool(who.get("emailVerified")),
        avatar_url=who.get("avatarUrl") or None,
        orgs=orgs,
        role=role,
        can_write=can_write,
        orgs_without_write=without,
    )


def check_token(username: str, token: str) -> TokenInfo:
    """Check ``token`` with the Hub for ``username``; :class:`SignInRefused`
    when it can't sign that user in, :class:`HubUnavailable` when the Hub
    didn't answer."""
    check_token_shape(token)
    who = whoami_fetcher(token)
    info = token_info(who)
    if who.get("type", "user") != "user" or not info.hf_id or not info.username:
        raise SignInRefused("token_invalid", "Hugging Face rejected this token")
    if info.username.lower() != username.strip().lower():
        raise SignInRefused(
            "token_other_account", "This token belongs to another account"
        )
    if not info.can_write:
        raise SignInRefused(
            "token_read_only",
            "This token can't write to your account: create a write token",
            status=403,
        )
    return info


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _email_for(db: Session, info: TokenInfo, user: Optional[User]) -> Optional[str]:
    """The Hub's email, kept only when it is verified and no other account holds
    it (an account is never joined by email)."""
    if not info.email or not info.email_verified:
        return user.email if user else None
    email = info.email.lower()
    holder = db.query(User).filter(User.email == email).first()
    if holder is not None and (user is None or holder.id != user.id):
        return user.email if user else None
    return email


SignupCheck = Callable[[TokenInfo], Optional[SignInRefused]]


def _default_signup_check(info: TokenInfo) -> Optional[SignInRefused]:
    """The backoffice's sign-up policy (services/platform.py)."""
    from server.services import platform

    refused = platform.check_signup(
        info.username, info.orgs, fine_grained=info.role == "fineGrained"
    )
    if refused is None:
        return None
    return SignInRefused(refused[0], refused[1], status=403)


def sign_in(
    db: Session,
    username: str,
    token: str,
    *,
    ip: Optional[str] = None,
    signup_check: SignupCheck = _default_signup_check,
) -> User:
    """Sign ``username`` in with ``token``: the account is created on the first
    sign-in (if the sign-up policy allows it), found by its HF id afterwards,
    and the token stored (replacing a different one: how a token is rotated)."""
    from server.services import user_secrets
    from server.services.credentials import HF_TOKEN

    info = check_token(username, token)
    user = db.query(User).filter(User.hf_id == info.hf_id).first()
    if user is not None and not user.is_active:
        raise SignInRefused("account_disabled", "This account is disabled", 403)
    created = user is None
    if user is None:
        refused = signup_check(info)
        if refused is not None:
            raise refused
        user = User(
            hf_id=info.hf_id,
            role=UserRole.USER,
            provider=AuthProvider.HF,
            is_active=True,
        )
        db.add(user)
    user.hf_username = info.username
    user.hf_avatar_url = info.avatar_url
    user.email = _email_for(db, info, None if created else user)
    user.last_login_at = _now()
    db.commit()
    db.refresh(user)

    current = user_secrets.load_credentials(user.id).secret(HF_TOKEN)
    if current != token:
        user_secrets.set_secret(user.id, HF_TOKEN, token)
    user_secrets.record_check(user.id, HF_TOKEN, TOKEN_OK)
    settings = user_secrets.get_settings(user.id)
    if not settings.get("hf_namespace"):
        user_secrets.update_settings(user.id, {"hf_namespace": info.username})

    audit.record(
        db,
        "user.signup.hf" if created else "user.login.hf",
        actor=user,
        target=user,
        ip=ip,
        detail={"hf_username": info.username, "token_role": info.role},
    )
    return user


# --- re-checking stored tokens (before a publication, and once a day) --------

TOKEN_OK = "ok"  # noqa: S105 — states, not values
TOKEN_REVOKED = "revoked"  # noqa: S105
TOKEN_READ_ONLY = "read_only"  # noqa: S105
TOKEN_HUB_UNAVAILABLE = "hub_unavailable"  # noqa: S105
# The states that lock the account out (sessions end, schedules wait).
UNUSABLE_STATES = (TOKEN_REVOKED, TOKEN_READ_ONLY)

# A check is reused this long for the same token (keyed by its hash).
CHECK_CACHE_SECONDS = 600.0
# The daily sweep: tokens unchecked for this long, at most this many a sweep.
RECHECK_AFTER_SECONDS = 24 * 3600
RECHECK_BATCH = 50

_checks: Dict[str, tuple[float, str]] = {}


def clear_check_cache() -> None:
    _checks.clear()


def token_state(token: str) -> str:
    """What the Hub says of ``token`` now: ok, revoked, read_only, or
    hub_unavailable (a Hub outage, which never locks anybody out)."""
    import hashlib
    import time

    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _checks.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < CHECK_CACHE_SECONDS:
        return cached[1]
    try:
        info = token_info(whoami_fetcher(token))
    except SignInRefused:
        state = TOKEN_REVOKED
    except HubUnavailable:
        return TOKEN_HUB_UNAVAILABLE  # not cached: ask again next time
    else:
        state = TOKEN_OK if info.can_write else TOKEN_READ_ONLY
    _checks[key] = (now, state)
    return state


def _record_state(user_id: str, state: str) -> None:
    """Keep the check on the user's secret; an unusable token ends the
    sessions of an account that signs in with it (the HF users)."""
    from server.core.database import get_scoped_db
    from server.services import user_secrets
    from server.services.auth import end_all_sessions
    from server.services.credentials import HF_TOKEN

    previous = user_secrets.record_check(user_id, HF_TOKEN, state)
    if state not in UNUSABLE_STATES or previous == state:
        return
    with get_scoped_db() as db:
        user = db.get(User, user_id)
        if user is None:
            return
        audit.record(db, "user.hf_token_invalid", target=user, detail={"state": state})
        if user.provider == AuthProvider.HF:
            end_all_sessions(db, user)
    logger.warning("Hugging Face token of user %s is %s", user_id, state)


def check_stored_token(user_id: str) -> Optional[str]:
    """Check ``user_id``'s stored Hugging Face token and record the result.
    None when they have none."""
    from server.services import user_secrets
    from server.services.credentials import HF_TOKEN

    token = user_secrets.load_credentials(user_id).secret(HF_TOKEN)
    if not token:
        return None
    state = token_state(token)
    if state != TOKEN_HUB_UNAVAILABLE:
        _record_state(user_id, state)
    return state


class TokenUnusable(Exception):
    """The token can't publish any more: revoked, or downgraded to read."""


def ensure_can_publish(creds: Any) -> None:
    """Before a publication: refuse a token the Hub rejects or that lost write
    access (and record it), before anything is written. A Hub outage lets the
    publication try, and fail on its own if it must."""
    from server.services.credentials import HF_TOKEN

    token = creds.secret(HF_TOKEN)
    if not token:
        return
    state = token_state(token)
    if creds.user_id and state != TOKEN_HUB_UNAVAILABLE:
        _record_state(creds.user_id, state)
    if state == TOKEN_REVOKED:
        raise TokenUnusable(
            "Hugging Face rejected your token. Sign in again with a new token "
            "(or replace it in Settings)."
        )
    if state == TOKEN_READ_ONLY:
        raise TokenUnusable(
            "Your Hugging Face token can no longer write. Sign in again with a "
            "write token (or replace it in Settings)."
        )


def recheck_stale_tokens(now: Optional[datetime] = None) -> int:
    """The worker's daily sweep: check the stored HF tokens not checked for a
    day, a batch at a time (oldest first). Returns how many were checked."""
    from datetime import timedelta

    from sqlalchemy import or_, select

    from server.core.database import get_scoped_db
    from server.models.user_secret import UserSecret
    from server.services.credentials import HF_TOKEN

    now = now or _now()
    cutoff = (now - timedelta(seconds=RECHECK_AFTER_SECONDS)).replace(tzinfo=None)
    with get_scoped_db() as db:
        user_ids = list(
            db.scalars(
                select(UserSecret.user_id)
                .where(
                    UserSecret.kind == HF_TOKEN,
                    or_(
                        UserSecret.last_checked_at.is_(None),
                        UserSecret.last_checked_at < cutoff,
                    ),
                )
                .order_by(UserSecret.last_checked_at.asc().nulls_first())
                .limit(RECHECK_BATCH)
            )
        )
    checked = 0
    for user_id in user_ids:
        try:
            if check_stored_token(user_id) not in (None, TOKEN_HUB_UNAVAILABLE):
                checked += 1
        except Exception:  # noqa: BLE001 — one account's failure stops no other
            logger.exception("Hugging Face token check of user %s failed", user_id)
    return checked
