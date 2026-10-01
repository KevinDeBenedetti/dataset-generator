"""The backoffice: accounts and usage — never content, never secrets.

What an admin sees of a user is deliberately narrow: identity (email, sign-in
providers), role and status, dates, **counts** (datasets, pairs, runs) and which
kinds of keys are configured (booleans). Dataset names, pairs, settings values
and secrets are not reachable from here, and there is no impersonation.

Role/status changes keep at least one active admin (the admin rows are locked
while checking, so two concurrent demotions can't both pass), never touch an
``ADMIN_EMAILS`` account, and are audited.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from server.models.dataset import Dataset, QAPair
from server.models.identity import AuditLog, Identity
from server.models.job_run import JobRun
from server.models.user import SYSTEM_EMAIL, User, UserRole
from server.models.user_secret import UserSecret
from server.services import audit
from server.services.auth import end_all_sessions
from server.services.identities import is_locked_admin

logger = logging.getLogger(__name__)


class AdminError(ValueError):
    """A refused admin action; the message is safe to show."""


class NotFound(LookupError):
    pass


def _counts(db: Session, user_ids: List[str]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {
        uid: {"datasets": 0, "pairs": 0, "runs": 0} for uid in user_ids
    }
    if not user_ids:
        return out
    for owner, n in db.execute(
        select(Dataset.owner_id, func.count())
        .where(Dataset.owner_id.in_(user_ids))
        .group_by(Dataset.owner_id)
    ):
        out[owner]["datasets"] = n
    for owner, n in db.execute(
        select(Dataset.owner_id, func.count())
        .join(QAPair, QAPair.dataset_id == Dataset.id)
        .where(Dataset.owner_id.in_(user_ids))
        .group_by(Dataset.owner_id)
    ):
        out[owner]["pairs"] = n
    for owner, n in db.execute(
        select(JobRun.owner_id, func.count())
        .where(JobRun.owner_id.in_(user_ids))
        .group_by(JobRun.owner_id)
    ):
        out[owner]["runs"] = n
    return out


def _view(user: User, counts: Dict[str, int], providers: List[str], keys: List[str]):
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "locked": is_locked_admin(user),
        "providers": sorted(set(providers)),
        "has_password": bool(user.hashed_password),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "configured_keys": sorted(set(keys)),
        **counts,
    }


def list_users(
    db: Session, q: str = "", limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    query = select(User).where(User.email != SYSTEM_EMAIL)
    if q:
        query = query.where(User.email.ilike(f"%{q.strip().lower()}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = list(
        db.scalars(
            query.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
        )
    )
    ids = [u.id for u in users]
    counts = _counts(db, ids)
    providers: Dict[str, List[str]] = {i: [] for i in ids}
    keys: Dict[str, List[str]] = {i: [] for i in ids}
    if ids:
        for uid, provider in db.execute(
            select(Identity.user_id, Identity.provider).where(Identity.user_id.in_(ids))
        ):
            providers[uid].append(provider)
        for uid, kind in db.execute(
            select(UserSecret.user_id, UserSecret.kind).where(
                UserSecret.user_id.in_(ids)
            )
        ):
            keys[uid].append(kind)
    return {
        "total": total,
        "users": [_view(u, counts[u.id], providers[u.id], keys[u.id]) for u in users],
    }


def get_user(db: Session, user_id: str) -> Dict[str, Any]:
    user = db.get(User, user_id)
    if user is None or user.email == SYSTEM_EMAIL:
        raise NotFound(user_id)
    providers = list(
        db.scalars(select(Identity.provider).where(Identity.user_id == user_id))
    )
    keys = list(
        db.scalars(select(UserSecret.kind).where(UserSecret.user_id == user_id))
    )
    return _view(user, _counts(db, [user_id])[user_id], providers, keys)


def _target(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.email == SYSTEM_EMAIL:
        raise NotFound(user_id)
    return user


def _other_active_admins(db: Session, user: User) -> int:
    """Active admins besides ``user``, with the admin rows locked (Postgres)."""
    rows = db.scalars(
        select(User.id)
        .where(
            User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id
        )
        .with_for_update()
    )
    return len(list(rows))


def _guard_last_admin(db: Session, user: User) -> None:
    if (
        user.role == UserRole.ADMIN
        and user.is_active
        and _other_active_admins(db, user) == 0
    ):
        raise AdminError("This is the last active admin.")


def update_user(
    db: Session,
    actor: User,
    user_id: str,
    *,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    ip: Optional[str] = None,
) -> Dict[str, Any]:
    user = _target(db, user_id)
    if role is not None and role not in UserRole.ALL:
        raise AdminError(f"Unknown role '{role}'")
    changes_role = role is not None and role != user.role
    changes_active = is_active is not None and is_active != user.is_active
    if (changes_role or changes_active) and is_locked_admin(user):
        raise AdminError(
            "This account is listed in ADMIN_EMAILS: change that setting instead."
        )
    deactivating = changes_active and is_active is False
    if (changes_role and role != UserRole.ADMIN) or deactivating:
        _guard_last_admin(db, user)

    if role is not None and role != user.role:
        before = user.role
        user.role = role
        audit.record(
            db,
            "user.role_changed",
            actor=actor,
            target=user,
            ip=ip,
            detail={"from": before, "to": role},
            commit=False,
        )
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        audit.record(
            db,
            "user.activated" if is_active else "user.deactivated",
            actor=actor,
            target=user,
            ip=ip,
            commit=False,
        )
    db.commit()
    if deactivating:
        # Out at once: refresh tokens revoked, access tokens refused.
        end_all_sessions(db, user)
    return get_user(db, user_id)


def delete_account(
    db: Session, user: User, actor: Optional[User] = None, ip=None
) -> int:
    """Delete ``user`` and everything they own (cascade), then their Qdrant
    collections. Returns how many collections were dropped. Hugging Face repos
    they published are theirs and stay."""
    from server.services.qdrant import default_collection_name, delete_collection

    if is_locked_admin(user):
        raise AdminError(
            "This account is listed in ADMIN_EMAILS: remove it there first."
        )
    if (
        user.role == UserRole.ADMIN
        and user.is_active
        and _other_active_admins(db, user) == 0
    ):
        raise AdminError("This is the last active admin.")
    collections = [
        default_collection_name(d.id, d.qdrant_collection)
        for d in db.scalars(select(Dataset).where(Dataset.owner_id == user.id))
    ]
    audit.record(
        db,
        "user.deleted",
        actor=actor or user,
        target=user,
        ip=ip,
        detail={"datasets": len(collections), "self": actor is None},
        commit=False,
    )
    db.flush()
    db.delete(user)
    db.commit()
    dropped = 0
    for name in collections:
        try:
            dropped += 1 if delete_collection(name) else 0
        except Exception as exc:  # noqa: BLE001 — the account is gone either way
            logger.warning("Could not drop Qdrant collection %s: %s", name, exc)
    return dropped


def delete_user(db: Session, actor: User, user_id: str, ip=None) -> None:
    user = _target(db, user_id)
    if user.id == actor.id:
        raise AdminError("Delete your own account from Settings.")
    delete_account(db, user, actor=actor, ip=ip)


def usage(db: Session) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    users = db.execute(
        select(
            func.count(),
            func.count().filter(User.is_active.is_(True)),
            func.count().filter(User.role == UserRole.ADMIN),
            func.count().filter(User.last_login_at >= since),
        ).where(User.email != SYSTEM_EMAIL)
    ).one()
    runs: Dict[str, int] = {
        status: count
        for status, count in db.execute(
            select(JobRun.status, func.count())
            .where(JobRun.started_at >= since)
            .group_by(JobRun.status)
        )
    }
    return {
        "users": {
            "total": users[0],
            "active": users[1],
            "admins": users[2],
            "signed_in_30d": users[3],
        },
        "datasets": db.scalar(select(func.count()).select_from(Dataset)) or 0,
        "pairs": db.scalar(select(func.count()).select_from(QAPair)) or 0,
        "runs_30d": runs,
        "running": db.scalar(
            select(func.count()).select_from(JobRun).where(JobRun.status == "running")
        )
        or 0,
    }


def list_audit(
    db: Session,
    limit: int = 100,
    offset: int = 0,
    action: str = "",
    user_id: str = "",
) -> Dict[str, Any]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    if user_id:
        query = query.where(
            or_(AuditLog.actor_id == user_id, AuditLog.target_user_id == user_id)
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    entries = list(rows)
    emails: Dict[str, str] = {}
    ids = {e.actor_id for e in entries if e.actor_id} | {
        e.target_user_id for e in entries if e.target_user_id
    }
    if ids:
        emails = {
            u.id: u.email for u in db.scalars(select(User).where(User.id.in_(ids)))
        }
    return {
        "total": total,
        "entries": [
            {
                "id": e.id,
                "created_at": e.created_at,
                "action": e.action,
                "actor": emails.get(e.actor_id or "") or e.actor_label,
                "target": emails.get(e.target_user_id or "") or e.target_label,
                "target_user_id": e.target_user_id,
                "ip": e.ip,
                "detail": e.detail or {},
            }
            for e in entries
        ],
    }
