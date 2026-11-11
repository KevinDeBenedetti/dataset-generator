"""Job schedules: a job's saved options per user, and the runs the worker
queues by itself (models/job_schedule.py).

A schedule is one row per owner, job and scope — the resume Q&A job keeps one
per resume. It holds the options a run copies, the model, and an optional
preset at a time of day (UTC): every ``day``, every ``week`` (on Mondays) or
every ``month`` (on the 1st) — a fixed calendar, so a schedule never drifts.
The worker's loop calls :func:`queue_due` with its other sweeps: a due row is
claimed by moving its ``next_run_at`` on (a conditional update, so two workers
never queue the same tick), then its run is queued exactly as the page would,
with the owner's own keys and under the owner's quotas. A row whose preset is
off only keeps the options for the runs the user starts.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.core.database import get_scoped_db
from server.jobs.registry import JOBS
from server.models.job_run import JobRun
from server.models.job_schedule import JobSchedule
from server.models.user import User, UserRole
from server.services.jobs import QuotaExceededError, RunConflictError, queue_run

logger = logging.getLogger(__name__)

EVERY = ("day", "week", "month")


class ScheduleNotFoundError(LookupError):
    """No schedule of that job and scope among the caller's."""


class ScheduleInputError(ValueError):
    """A preset, an hour or a minute that doesn't exist."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # The database hands naive timestamps back (UTC by construction).
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- when ---------------------------------------------------------------------------


def _at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def next_run(every: str, hour: int, minute: int, after: datetime) -> datetime:
    """The first time strictly after ``after`` the preset runs, at
    ``hour``:``minute`` UTC: the next day, the next Monday, or the next 1st
    of a month. Counted from now by the sweep, so a worker that was down for
    a while runs a schedule once, not once per missed tick."""
    after = _aware(after)
    if every == "day":
        today = _at(after, hour, minute)
        return today if today > after else today + timedelta(days=1)
    if every == "week":
        monday = _at(after - timedelta(days=after.weekday()), hour, minute)
        return monday if monday > after else monday + timedelta(days=7)
    if every == "month":
        first = _at(after.replace(day=1), hour, minute)
        if first > after:
            return first
        if after.month == 12:
            return first.replace(year=after.year + 1, month=1)
        return first.replace(month=after.month + 1)
    raise ScheduleInputError(f"Unknown preset '{every}'")


# --- reading and saving -----------------------------------------------------------


def _latest_run(db: Session, row: JobSchedule) -> Optional[Dict[str, str]]:
    if not row.last_run_id:
        return None
    run = db.get(JobRun, row.last_run_id)
    return {"id": run.id, "status": run.status} if run else None


def _view(db: Session, row: JobSchedule) -> Dict[str, Any]:
    return {
        "id": row.id,
        "job": row.job_id,
        "scope": row.scope,
        "options": dict(row.options or {}),
        "model_ref": row.model_ref,
        "every": row.every,
        "at_hour": row.at_hour,
        "at_minute": row.at_minute,
        "publish": row.publish,
        "next_run_at": _aware(row.next_run_at) if row.next_run_at else None,
        "last_run": _latest_run(db, row),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _owned(db: Session, owner_id: str, job_id: str, scope: str) -> JobSchedule:
    row = db.scalar(
        select(JobSchedule).where(
            JobSchedule.owner_id == owner_id,
            JobSchedule.job_id == job_id,
            JobSchedule.scope == scope,
        )
    )
    if row is None:
        raise ScheduleNotFoundError(f"No schedule of {job_id} for '{scope}'")
    return row


def get_schedule(db: Session, owner_id: str, job_id: str, scope: str) -> Dict[str, Any]:
    return _view(db, _owned(db, owner_id, job_id, scope))


def list_schedules(db: Session, owner_id: str) -> List[Dict[str, Any]]:
    """The caller's schedules, most recently edited first (the data export)."""
    rows = db.scalars(
        select(JobSchedule)
        .where(JobSchedule.owner_id == owner_id)
        .order_by(JobSchedule.updated_at.desc())
    )
    return [_view(db, r) for r in rows]


def upsert_schedule(
    db: Session,
    owner_id: str,
    job_id: str,
    scope: str,
    *,
    options: Dict[str, Any],
    model_ref: Optional[str] = None,
    every: Optional[str] = None,
    at_hour: int = 3,
    at_minute: int = 0,
    publish: bool = False,
) -> Dict[str, Any]:
    """Save the options (checked against the job's), the model and the
    preset; a preset set or moved runs first at its next time from now."""
    spec = JOBS.get(job_id)
    if spec is None:
        raise ScheduleInputError(f"Unknown job '{job_id}'")
    try:
        parsed = spec.options.model_validate(options)
    except ValidationError as exc:
        raise ScheduleInputError(exc.errors(include_url=False)[0]["msg"]) from exc
    if every is not None and every not in EVERY:
        raise ScheduleInputError(f"The preset is one of {', '.join(EVERY)}, or none")
    if not 0 <= at_hour <= 23 or not 0 <= at_minute <= 59:
        raise ScheduleInputError("The time is an hour (0-23) and a minute (0-59) UTC")

    try:
        row = _owned(db, owner_id, job_id, scope)
    except ScheduleNotFoundError:
        row = JobSchedule(owner_id=owner_id, job_id=job_id, scope=scope)
        db.add(row)
    moved = (row.every, row.at_hour, row.at_minute) != (every, at_hour, at_minute)
    row.options = parsed.model_dump(mode="json")
    row.model_ref = model_ref or None
    row.every = every
    row.at_hour = at_hour
    row.at_minute = at_minute
    row.publish = bool(publish)
    if every is None:
        row.next_run_at = None
    elif moved or row.next_run_at is None:
        row.next_run_at = next_run(every, at_hour, at_minute, _now())
    db.commit()
    db.refresh(row)
    return _view(db, row)


def delete_schedule(db: Session, owner_id: str, job_id: str, scope: str) -> None:
    db.delete(_owned(db, owner_id, job_id, scope))
    db.commit()


def record_run(
    db: Session, owner_id: str, job_id: str, scope: str, run_id: str
) -> None:
    """Remember a run the user started as the schedule's latest."""
    row = _owned(db, owner_id, job_id, scope)
    row.last_run_id = run_id
    db.commit()


# --- the sweep (worker) ---------------------------------------------------------------


def _may_run(db: Session, row: JobSchedule) -> Optional[str]:
    """Why the owner can't have this run now, or None."""
    spec = JOBS.get(row.job_id)
    if spec is None:
        return f"unknown job '{row.job_id}'"
    owner = db.get(User, row.owner_id)
    if owner is None or not owner.is_active:
        return "its owner's account is disabled"
    if spec.admin_only and owner.role != UserRole.ADMIN:
        return "its owner is no longer an admin"
    return None


def queue_due(now: Optional[datetime] = None) -> List[str]:
    """Queue a run of every schedule whose time has come; the ids queued.

    Blocking — the worker calls it from a thread. A schedule the worker can't
    run now (a run of its job in progress, the owner's quota reached, a model
    that isn't usable any more) is logged and tried again next time; its date
    has already moved on, so a stuck schedule never floods the queue.
    """
    from server.services.credentials import resolve_credentials

    now = now or _now()
    queued: List[str] = []
    with get_scoped_db() as db:
        due = list(
            db.scalars(
                select(JobSchedule).where(
                    JobSchedule.every.is_not(None),
                    JobSchedule.next_run_at.is_not(None),
                    JobSchedule.next_run_at <= now,
                )
            )
        )
        for row in due:
            every = row.every or "day"
            seen = row.next_run_at
            claimed = db.execute(
                update(JobSchedule)
                .where(JobSchedule.id == row.id, JobSchedule.next_run_at == seen)
                .values(next_run_at=next_run(every, row.at_hour, row.at_minute, now))
            ).rowcount
            db.commit()
            if not claimed:
                continue  # another worker's tick
            reason = _may_run(db, row)
            if reason:
                logger.warning(
                    "schedule %s (%s) skipped: %s", row.id, row.job_id, reason
                )
                continue
            options = {**(row.options or {}), "publish": row.publish}
            try:
                creds = resolve_credentials(row.owner_id)
                run = queue_run(row.owner_id, creds, row.job_id, options, row.model_ref)
            except (RunConflictError, QuotaExceededError, ValueError) as exc:
                logger.warning("schedule %s (%s) skipped: %s", row.id, row.job_id, exc)
                continue
            except Exception:  # noqa: BLE001 — one schedule's failure stops no other
                logger.exception(
                    "schedule %s (%s) could not be queued", row.id, row.job_id
                )
                continue
            row.last_run_id = run["id"]
            db.commit()
            queued.append(run["id"])
            logger.info(
                "schedule %s queued run %s of %s", row.id, run["id"], row.job_id
            )
    return queued
