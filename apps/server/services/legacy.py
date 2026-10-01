"""Hand the pre-multi-user data to a real account.

The ownership migration gives every existing dataset, job run, model default and
quality rule to the oldest active admin — or, when there was none, to the
inactive ``system`` user (see ``models.user.SYSTEM_EMAIL``). This moves whatever
the system user still holds to a real account.
"""

from typing import Dict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.models.dataset import Dataset
from server.models.job_run import JobRun
from server.models.model_defaults import ModelDefault
from server.models.quality_rules import QualityRules
from server.models.user import SYSTEM_EMAIL
from server.services.users import get_user_by_email


def _free_name(db: Session, owner_id: str, name: str) -> str:
    """``name``, or ``name-legacy[-n]`` when the target already has one by that name."""
    taken = set(db.scalars(select(Dataset.name).where(Dataset.owner_id == owner_id)))
    if name not in taken:
        return name
    candidate, n = f"{name}-legacy", 2
    while candidate in taken:
        candidate, n = f"{name}-legacy-{n}", n + 1
    return candidate


def claim_legacy_rows(db: Session, email: str) -> Dict[str, int]:
    """Move everything the ``system`` user owns to ``email``'s account.

    Datasets keep their name unless the target already has one by that name
    (then ``-legacy`` is appended). A model default or quality rule the target
    already set wins over the legacy one. Raises ValueError for an unknown
    target or when the target is the system user itself.
    """
    target = get_user_by_email(db, email)
    if target is None:
        raise ValueError(f"No account with the email '{email}'")
    if target.email == SYSTEM_EMAIL:
        raise ValueError("The system user cannot claim its own data")

    system = get_user_by_email(db, SYSTEM_EMAIL)
    counts = {"datasets": 0, "job_runs": 0, "model_defaults": 0, "quality_rules": 0}
    if system is None:
        return counts

    for dataset in db.scalars(select(Dataset).where(Dataset.owner_id == system.id)):
        dataset.name = _free_name(db, target.id, dataset.name)
        dataset.owner_id = target.id
        db.flush()
        counts["datasets"] += 1

    runs = db.execute(
        update(JobRun).where(JobRun.owner_id == system.id).values(owner_id=target.id)
    )
    counts["job_runs"] = getattr(runs, "rowcount", 0) or 0

    have = set(
        db.scalars(select(ModelDefault.role).where(ModelDefault.user_id == target.id))
    )
    for default in db.scalars(
        select(ModelDefault).where(ModelDefault.user_id == system.id)
    ):
        if default.role in have:
            db.delete(default)
        else:
            default.user_id = target.id
            counts["model_defaults"] += 1
        db.flush()

    rules = db.get(QualityRules, system.id)
    if rules is not None:
        if db.get(QualityRules, target.id) is None:
            rules.user_id = target.id
            counts["quality_rules"] = 1
        else:
            db.delete(rules)
        db.flush()

    # Nothing is left: the placeholder has done its job.
    db.delete(system)
    db.commit()
    return counts
