"""Start, read, cancel and publish the runs of ``server.jobs.registry``.

The jobs are the same code their GitHub Actions workflows run on a schedule.
From the Jobs page a run is *queued* here; a worker executes it
(services/queue.py) and the page polls its row in ``job_runs``. A draft job's
run stops at a draft, published later by :func:`publish_run` — exactly what
was reviewed, never a regeneration.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from server.core.config import config

from server.core.database import get_scoped_db
from server.jobs.registry import JOBS, JobSpec
from server.models.job_run import JobRun
from server.services.model_defaults import resolve_model
from server.services.credentials import Credentials
from server.services.providers import get_provider, parse_ref, validate_ref

logger = logging.getLogger(__name__)


class UnknownJobError(KeyError):
    pass


class UnknownRunError(KeyError):
    pass


class RunConflictError(RuntimeError):
    """A run of this job is already in progress, or the run can't be published."""


class QuotaExceededError(RuntimeError):
    """The user has used up a quota (QUOTA_* settings); the message says which."""


def _spec(job_id: str) -> JobSpec:
    try:
        return JOBS[job_id]
    except KeyError:
        raise UnknownJobError(job_id) from None


def _model_missing(spec: JobSpec, model_ref: str, creds: Credentials) -> List[str]:
    if not spec.uses_model or not model_ref:
        return []
    try:
        return get_provider(parse_ref(model_ref)[0]).missing(creds)
    except Exception:  # noqa: BLE001 — an invalid ref is reported at run time
        return []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(row: JobRun) -> str:
    return row.status


def _to_dict(row: JobRun, with_preview: bool = True) -> Dict[str, Any]:
    spec = JOBS.get(row.job_id)
    preview = None
    if with_preview and row.draft and spec and spec.preview:
        preview = spec.preview(row.draft)
    return {
        "id": row.id,
        "job": row.job_id,
        "status": _status(row),
        "options": row.options or {},
        "model_ref": row.model_ref,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "progress": row.progress if row.status in ("queued", "running") else None,
        "cancel_requested": bool(row.cancel_requested),
        "result": row.result,
        "error": row.error,
        "has_draft": row.draft is not None,
        "preview": preview,
        "published_url": row.published_url,
        "published_at": row.published_at,
    }


def _latest_row(db, owner_id: str, job_id: str) -> Optional[JobRun]:
    return (
        db.query(JobRun)
        .filter(JobRun.owner_id == owner_id, JobRun.job_id == job_id)
        .order_by(JobRun.started_at.desc())
        .first()
    )


def _owned_row(db, owner_id: str, run_id: str) -> JobRun:
    """The owner's run, or :class:`UnknownRunError` — which is also how another
    user's run looks, so a foreign run id reveals nothing."""
    row = db.get(JobRun, run_id)
    if row is None or row.owner_id != owner_id:
        raise UnknownRunError(run_id)
    return row


def list_jobs(owner_id: str, creds: Credentials) -> List[Dict[str, Any]]:
    """Every job with its option schema, configuration status and the owner's
    latest run."""
    default_model = resolve_model("jobs", user_id=owner_id)
    latest: Dict[str, Dict[str, Any]] = {}
    try:
        with get_scoped_db() as db:
            for job_id in JOBS:
                row = _latest_row(db, owner_id, job_id)
                if row is not None:
                    latest[job_id] = {"id": row.id, "status": _status(row)}
    except Exception as exc:  # noqa: BLE001 — the catalogue must still load
        logger.warning("Could not read job runs: %s", exc)

    out = []
    for spec in JOBS.values():
        missing = spec.missing(creds) + _model_missing(spec, default_model, creds)
        out.append(
            {
                "id": spec.id,
                "title": spec.title,
                "description": spec.description,
                "workflow": spec.workflow,
                "schedule": spec.schedule,
                "uses_model": spec.uses_model,
                "default_model": default_model if spec.uses_model else None,
                "has_draft": spec.publisher is not None,
                "configured": not missing,
                "missing": missing,
                "options_schema": spec.options.model_json_schema(),
                "latest_run": latest.get(spec.id),
            }
        )
    return out


def _check_quotas(db, owner_id: str) -> None:
    if config.quota_active_runs:
        active = (
            db.query(JobRun)
            .filter(
                JobRun.owner_id == owner_id, JobRun.status.in_(("queued", "running"))
            )
            .count()
        )
        if active >= config.quota_active_runs:
            raise QuotaExceededError(
                f"You already have {active} run(s) in progress "
                f"(limit {config.quota_active_runs}). Wait for one to finish."
            )
    if config.quota_runs_per_day:
        since = _now() - timedelta(days=1)
        today = (
            db.query(JobRun)
            .filter(JobRun.owner_id == owner_id, JobRun.started_at >= since)
            .count()
        )
        if today >= config.quota_runs_per_day:
            raise QuotaExceededError(
                f"Daily limit reached ({config.quota_runs_per_day} runs in 24 h)."
            )


async def start_run(
    owner_id: str,
    creds: Credentials,
    job_id: str,
    options: Dict[str, Any],
    model_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and queue a run; returns at once (status "queued").

    The credentials are only used to fail fast on an unusable model; the worker
    resolves the owner's credentials itself when it runs the job.

    Raises :class:`UnknownJobError`, pydantic ``ValidationError`` for bad
    options, ``ValueError`` for an unusable model reference,
    :class:`RunConflictError` when a run of this job is queued or running, and
    :class:`QuotaExceededError`.
    """
    spec = _spec(job_id)
    parsed = spec.options.model_validate(options or {})
    model = (
        validate_ref(resolve_model("jobs", model_ref, user_id=owner_id), creds)
        if spec.uses_model
        else None
    )

    with get_scoped_db() as db:
        active = (
            db.query(JobRun)
            .filter(
                JobRun.owner_id == owner_id,
                JobRun.job_id == job_id,
                JobRun.status.in_(("queued", "running")),
            )
            .first()
        )
        if active is not None:
            raise RunConflictError(f"A {job_id} run is already in progress")
        _check_quotas(db, owner_id)
        row = JobRun(
            owner_id=owner_id,
            job_id=job_id,
            status="queued",
            options=parsed.model_dump(mode="json"),
            model_ref=model,
            progress={"done": 0, "total": 0, "label": "Waiting for a worker…"},
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Lost the race: the unique index on active runs let one insert win.
            db.rollback()
            raise RunConflictError(f"A {job_id} run is already in progress") from None
        run_id = row.id

    return get_run(owner_id, run_id)


def cancel_run(owner_id: str, run_id: str) -> Dict[str, Any]:
    """Cancel a queued run at once, or ask the worker to stop a running one."""
    with get_scoped_db() as db:
        row = _owned_row(db, owner_id, run_id)
        if row.status == "queued":
            done = db.execute(
                update(JobRun)
                .where(JobRun.id == run_id, JobRun.status == "queued")
                .values(status="cancelled", finished_at=_now(), progress=None)
            ).rowcount
            if not done:  # claimed meanwhile: cancel the running run instead
                row.cancel_requested = True
        elif row.status == "running":
            row.cancel_requested = True
        else:
            raise RunConflictError(f"This run is {row.status}, nothing to cancel")
        db.commit()
    return get_run(owner_id, run_id)


def _update(run_id: str, **fields: Any) -> None:
    with get_scoped_db() as db:
        row = db.get(JobRun, run_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def get_run(owner_id: str, run_id: str) -> Dict[str, Any]:
    with get_scoped_db() as db:
        return _to_dict(_owned_row(db, owner_id, run_id))


async def publish_run(
    owner_id: str,
    creds: Credentials,
    run_id: str,
    exclude: Sequence[str] = (),
    promote: Sequence[str] = (),
) -> Dict[str, Any]:
    """Publish a run's reviewed draft: ``exclude`` drops new pairs, ``promote``
    moves pairs from the review list into the export.

    Raises :class:`UnknownRunError`, :class:`RunConflictError` for a run
    without an unpublished draft, or the job's own ``JobError``.
    """
    with get_scoped_db() as db:
        row = _owned_row(db, owner_id, run_id)
        spec = JOBS.get(row.job_id)
        if spec is None or spec.publisher is None or row.draft is None:
            raise RunConflictError("This run has no draft to publish")
        # Atomic hand-off: of two concurrent publishes, one wins, the other 409s.
        taken = db.execute(
            update(JobRun)
            .where(JobRun.id == run_id, JobRun.status == "succeeded")
            .values(status="publishing")
        ).rowcount
        db.commit()
        if not taken:
            raise RunConflictError(f"This run is {row.status}, not ready to publish")
        draft = row.draft

    try:
        result = await spec.publisher(creds, draft, exclude, promote)
    except BaseException:
        _update(run_id, status="succeeded")  # still publishable after a failure
        raise
    _update(
        run_id,
        status="published",
        result=result.model_dump(mode="json"),
        published_url=result.url,
        published_at=_now(),
    )
    return get_run(owner_id, run_id)
