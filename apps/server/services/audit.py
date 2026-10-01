"""The security audit trail (``audit_log``): sign-ups, links, role changes…

Entries name accounts by id plus a short hash of the email (so the trail still
reads after a deletion, without keeping the address). ``detail`` holds small,
non-sensitive facts — never content, keys or tokens.
"""

import hashlib
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from server.models.identity import AuditLog
from server.models.user import User

logger = logging.getLogger(__name__)


def label_for(user: Optional[User]) -> Optional[str]:
    if user is None:
        return None
    return "email:" + hashlib.sha256(user.email.lower().encode()).hexdigest()[:16]


def record(
    db: Session,
    action: str,
    *,
    actor: Optional[User] = None,
    target: Optional[User] = None,
    ip: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    commit: bool = True,
) -> AuditLog:
    """Append one entry (committed unless the caller batches it)."""
    entry = AuditLog(
        action=action,
        actor_id=actor.id if actor else None,
        actor_label=label_for(actor),
        target_user_id=target.id if target else None,
        target_label=label_for(target),
        ip=ip,
        detail=detail or {},
    )
    db.add(entry)
    if commit:
        db.commit()
    logger.info(
        "audit %s actor=%s target=%s", action, entry.actor_id, entry.target_user_id
    )
    return entry
