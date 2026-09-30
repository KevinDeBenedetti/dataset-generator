"""Run the dataset jobs of ``server.jobs.registry`` on demand, in the background.

The jobs are the same code their GitHub Actions workflows run on a schedule.
From the Jobs page a run is started here and executes as a task of the server
process; its row in ``job_runs`` (see ``server.models.job_run``) is what the
page polls. A draft job's run stops at a draft, published later by
:func:`publish_run` — exactly what was reviewed, never a regeneration.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from server.core.database import get_scoped_db
from server.jobs.registry import JOBS, JobSpec
from server.models.job_run import JobRun
from server.services.model_defaults import resolve_model
from server.services.providers import get_provider, parse_ref, validate_ref

logger = logging.getLogger(__name__)

# Runs executing in this process, with their live progress. A "running" row
# whose id is missing here was cut short by a server restart.
_TASKS: Dict[str, asyncio.Task] = {}
_PROGRESS: Dict[str, Dict[str, Any]] = {}


class UnknownJobError(KeyError):
    pass


class UnknownRunError(KeyError):
    pass


class RunConflictError(RuntimeError):
    """A run of this job is already in progress, or the run can't be published."""


def _spec(job_id: str) -> JobSpec:
    try:
        return JOBS[job_id]
    except KeyError:
        raise UnknownJobError(job_id) from None


def _model_missing_env(spec: JobSpec, model_ref: str) -> List[str]:
    if not spec.uses_model or not model_ref:
        return []
    try:
        return get_provider(parse_ref(model_ref)[0]).missing_env()
    except Exception:  # noqa: BLE001 — an invalid ref is reported at run time
        return []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(row: JobRun) -> str:
    if row.status == "running" and row.id not in _TASKS:
        return "interrupted"
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
        "progress": _PROGRESS.get(row.id),
        "result": row.result,
        "error": row.error,
        "has_draft": row.draft is not None,
        "preview": preview,
        "published_url": row.published_url,
        "published_at": row.published_at,
    }


def _latest_row(db, job_id: str) -> Optional[JobRun]:
    return (
        db.query(JobRun)
        .filter(JobRun.job_id == job_id)
        .order_by(JobRun.started_at.desc())
        .first()
    )


def list_jobs() -> List[Dict[str, Any]]:
    """Every job with its option schema, configuration status and latest run."""
    default_model = resolve_model("jobs")
    latest: Dict[str, Dict[str, Any]] = {}
    try:
        with get_scoped_db() as db:
            for job_id in JOBS:
                row = _latest_row(db, job_id)
                if row is not None:
                    latest[job_id] = {"id": row.id, "status": _status(row)}
    except Exception as exc:  # noqa: BLE001 — the catalogue must still load
        logger.warning("Could not read job runs: %s", exc)

    out = []
    for spec in JOBS.values():
        missing = spec.missing_env() + _model_missing_env(spec, default_model)
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
                "missing_env": missing,
                "options_schema": spec.options.model_json_schema(),
                "latest_run": latest.get(spec.id),
            }
        )
    return out


async def start_run(
    job_id: str, options: Dict[str, Any], model_ref: Optional[str] = None
) -> Dict[str, Any]:
    """Validate, record and launch a run; returns at once (status "running").

    Raises :class:`UnknownJobError`, pydantic ``ValidationError`` for bad
    options, ``ValueError`` for an unusable model reference, and
    :class:`RunConflictError` when a run of this job is still in progress.
    """
    spec = _spec(job_id)
    parsed = spec.options.model_validate(options or {})
    model = validate_ref(resolve_model("jobs", model_ref)) if spec.uses_model else None

    with get_scoped_db() as db:
        latest = _latest_row(db, job_id)
        if latest is not None and _status(latest) == "running":
            raise RunConflictError(f"A {job_id} run is already in progress")
        row = JobRun(
            job_id=job_id,
            status="running",
            options=parsed.model_dump(mode="json"),
            model_ref=model,
        )
        db.add(row)
        db.commit()
        run_id = row.id

    _PROGRESS[run_id] = {"done": 0, "total": 0, "label": "Starting…"}

    def progress(done: int, total: int, label: str) -> None:
        _PROGRESS[run_id] = {"done": done, "total": total, "label": label}

    async def execute() -> None:
        try:
            outcome = await spec.runner(parsed, model, progress)
            changes: Dict[str, Any] = {
                "status": "succeeded",
                "result": outcome.result.model_dump(mode="json"),
                "draft": outcome.draft,
                "published_url": None if outcome.draft else outcome.result.url,
                "published_at": None
                if outcome.draft or not outcome.result.url
                else _now(),
            }
        except Exception as exc:  # noqa: BLE001 — recorded on the run, shown on the page
            logger.exception("Job %s run %s failed", job_id, run_id)
            changes = {"status": "failed", "error": str(exc)}
        finally:
            _PROGRESS.pop(run_id, None)
        _update(run_id, finished_at=_now(), **changes)
        _TASKS.pop(run_id, None)

    _TASKS[run_id] = asyncio.create_task(execute())
    return get_run(run_id)


def _update(run_id: str, **fields: Any) -> None:
    with get_scoped_db() as db:
        row = db.get(JobRun, run_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def get_run(run_id: str) -> Dict[str, Any]:
    with get_scoped_db() as db:
        row = db.get(JobRun, run_id)
        if row is None:
            raise UnknownRunError(run_id)
        return _to_dict(row)


async def publish_run(
    run_id: str, exclude: Sequence[str] = (), promote: Sequence[str] = ()
) -> Dict[str, Any]:
    """Publish a run's reviewed draft: ``exclude`` drops new pairs, ``promote``
    moves pairs from the review list into the export.

    Raises :class:`UnknownRunError`, :class:`RunConflictError` for a run
    without an unpublished draft, or the job's own ``JobError``.
    """
    with get_scoped_db() as db:
        row = db.get(JobRun, run_id)
        if row is None:
            raise UnknownRunError(run_id)
        spec = JOBS.get(row.job_id)
        if spec is None or spec.publisher is None or row.draft is None:
            raise RunConflictError("This run has no draft to publish")
        if row.status != "succeeded":
            raise RunConflictError(f"This run is {_status(row)}, not ready to publish")
        draft = row.draft

    result = await spec.publisher(draft, exclude, promote)
    _update(
        run_id,
        status="published",
        result=result.model_dump(mode="json"),
        published_url=result.url,
        published_at=_now(),
    )
    return get_run(run_id)
