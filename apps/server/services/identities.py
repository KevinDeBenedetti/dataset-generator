"""Which account an SSO sign-in lands on — the account-linking policy.

For an :class:`~server.services.sso.ExternalIdentity` coming back from a provider:

1. **Known identity** — ``(provider, subject)`` already linked: that account.
2. **Linking** (the user started the flow from Settings while signed in): the
   identity joins *that* account, unless it already belongs to another one.
3. **Trusted email** — the provider says the email is verified *and* the
   provider is a trusted one (Infomaniak, GitHub): the account with that email
   (this is how an existing password account starts using SSO). Audited.
4. **Sign-up** — a new account, only with a verified email, when sign-up is
   open and the domain allowed (backoffice platform switches).
   ``ADMIN_EMAILS`` can always sign up.

An unverified email never links and never creates an account: otherwise anyone
could register a victim's address at a provider and sign in as them.

After any successful sign-in, an account whose email is in ``ADMIN_EMAILS`` is
made admin, and — the first time — receives the data the ownership migration
parked on the ``system`` user.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.identity import Identity
from server.models.user import SYSTEM_EMAIL, User, UserRole
from server.services import audit, platform
from server.services.sso import ExternalIdentity
from server.services.users import get_user_by_email

logger = logging.getLogger(__name__)


class LoginRefused(Exception):
    """The sign-in can't proceed; ``code`` is passed to the login page."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_admin_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return email.lower() in config.admin_emails


def is_locked_admin(user: User) -> bool:
    """An ``ADMIN_EMAILS`` account: its role and status can't be changed in the app."""
    return is_admin_email(user.email)


def _find(db: Session, provider: str, subject: str) -> Optional[Identity]:
    return db.scalar(
        select(Identity).where(
            Identity.provider == provider, Identity.subject == subject
        )
    )


def _attach(db: Session, user: User, ext: ExternalIdentity) -> Identity:
    row = Identity(
        user_id=user.id,
        provider=ext.provider,
        subject=ext.subject,
        email=ext.email or None,
        email_verified=ext.email_verified,
        username=ext.username,
    )
    db.add(row)
    return row


def _may_sign_up(email: str) -> None:
    if is_admin_email(email):
        return
    if not platform.allow_signup():
        raise LoginRefused("signup_closed", "New accounts are not open at the moment.")
    domains = platform.allowed_email_domains()
    if domains and email.rsplit("@", 1)[-1] not in domains:
        raise LoginRefused(
            "domain_not_allowed", "Accounts are limited to certain email domains."
        )


def _after_login(db: Session, user: User, ip: Optional[str]) -> None:
    """Admin bootstrap, legacy data hand-over, bookkeeping."""
    if is_admin_email(user.email) and user.role != UserRole.ADMIN:
        user.role = UserRole.ADMIN
        audit.record(
            db,
            "user.promoted",
            target=user,
            ip=ip,
            detail={"reason": "ADMIN_EMAILS"},
            commit=False,
        )
    user.last_login_at = _now()
    db.commit()

    if is_admin_email(user.email) and get_user_by_email(db, SYSTEM_EMAIL) is not None:
        from server.services.legacy import claim_legacy_rows

        counts = claim_legacy_rows(db, user.email)
        audit.record(db, "legacy.claimed", target=user, ip=ip, detail=counts)


def resolve_login(
    db: Session,
    ext: ExternalIdentity,
    *,
    link_to: Optional[User] = None,
    ip: Optional[str] = None,
) -> User:
    """The account ``ext`` signs in to (see the module docstring). Raises
    :class:`LoginRefused`."""
    known = _find(db, ext.provider, ext.subject)

    if link_to is not None:
        if known is not None and known.user_id != link_to.id:
            raise LoginRefused(
                "identity_in_use",
                f"This {ext.provider} account is already linked to another account.",
            )
        if known is None:
            known = _attach(db, link_to, ext)
            audit.record(
                db,
                "identity.linked",
                actor=link_to,
                target=link_to,
                ip=ip,
                detail={"provider": ext.provider},
                commit=False,
            )
        user = link_to
    elif known is not None:
        user = db.get(User, known.user_id)
        assert user is not None  # FK + cascade
    else:
        email = ext.email if ext.email_verified else ""
        if not email:
            raise LoginRefused(
                "no_verified_email",
                f"Your {ext.provider} account has no verified email address.",
            )
        existing = get_user_by_email(db, email)
        if existing is not None:
            if ext.provider not in config.sso_trusted_email_providers:
                raise LoginRefused(
                    "link_required",
                    "An account with this email exists: sign in to it, then link "
                    f"{ext.provider} from Settings.",
                )
            if existing.email == SYSTEM_EMAIL:
                raise LoginRefused("no_verified_email", "This address is reserved.")
            user = existing
            known = _attach(db, user, ext)
            audit.record(
                db,
                "identity.autolinked",
                target=user,
                ip=ip,
                detail={"provider": ext.provider},
                commit=False,
            )
        else:
            _may_sign_up(email)
            user = User(email=email, role=UserRole.USER, provider=ext.provider)
            db.add(user)
            db.flush()
            known = _attach(db, user, ext)
            audit.record(
                db,
                "user.signup",
                target=user,
                ip=ip,
                detail={"provider": ext.provider},
                commit=False,
            )

    if not user.is_active:
        db.rollback()
        raise LoginRefused("account_disabled", "This account is disabled.")

    known.email = ext.email or known.email
    known.email_verified = ext.email_verified
    known.username = ext.username or known.username
    known.last_login_at = _now()
    _after_login(db, user, ip)
    db.refresh(user)
    return user


def list_identities(db: Session, user: User) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Identity)
        .where(Identity.user_id == user.id)
        .order_by(Identity.created_at)
    )
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "email": r.email,
            "username": r.username,
            "created_at": r.created_at,
            "last_login_at": r.last_login_at,
        }
        for r in rows
    ]


def login_methods(db: Session, user: User) -> int:
    """How many ways ``user`` can still sign in."""
    identities = len(list_identities(db, user))
    password = 1 if (user.hashed_password and config.enable_local_login) else 0
    return identities + password


def unlink_identity(
    db: Session, user: User, identity_id: str, ip: Optional[str] = None
) -> None:
    """Remove one of ``user``'s identities. ValueError: not theirs (→ 404);
    LookupError: it is their last way in (→ 409)."""
    row = db.get(Identity, identity_id)
    if row is None or row.user_id != user.id:
        raise ValueError("Unknown identity")
    if login_methods(db, user) <= 1:
        raise LookupError("You can't remove your only way to sign in.")
    db.delete(row)
    audit.record(
        db,
        "identity.unlinked",
        actor=user,
        target=user,
        ip=ip,
        detail={"provider": row.provider},
    )
