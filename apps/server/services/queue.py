"""The job queue: ``job_runs`` rows, claimed and executed by workers.

* The API inserts a run ``queued`` (services/jobs.py) and only ever reads it
  back; it never executes anything.
* A worker (``python -m server.worker``, or :func:`run_forever`) claims the
  oldest queued run with ``SELECT … FOR UPDATE SKIP LOCKED`` — two workers can
  never take the same run — marks it ``running`` and executes it.
* The worker resolves the **owner's** credentials itself, at execution time;
  nothing secret is ever stored in the row.
* While running it heart-beats (and writes throttled progress) every few
  seconds and checks ``cancel_requested``. A run whose heartbeat goes stale
  (the worker was killed) becomes ``interrupted`` — never re-run automatically:
  it may already have spent model quota or published something.
* On SIGTERM a worker stops claiming and lets its current runs finish for
  ``WORKER_DRAIN_SECONDS``; whatever is still running then is left to the
  stale-heartbeat sweep.
"""

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update

from server.core.config import config
from server.core.database import get_scoped_db
from server.core.redact import redact
from server.jobs.registry import JOBS
from server.models.job_run import JobRun

logger = logging.getLogger(__name__)

ACTIVE = ("queued", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def claim_next(worker: str) -> Optional[str]:
    """Take the oldest queued run (or None). Safe with any number of workers."""
    with get_scoped_db() as db:
        row = db.scalar(
            select(JobRun)
            .where(JobRun.status == "queued")
            .order_by(JobRun.started_at, JobRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            db.rollback()
            return None
        now = _now()
        row.status = "running"
        row.claimed_by = worker
        row.claimed_at = now
        row.heartbeat_at = now
        row.progress = {"done": 0, "total": 0, "label": "Starting…"}
        db.commit()
        return row.id


def reap_stale(stale_after: Optional[float] = None) -> int:
    """Mark running runs whose worker stopped heart-beating as interrupted."""
    cutoff = _now() - timedelta(seconds=stale_after or config.worker_stale_seconds)
    with get_scoped_db() as db:
        count = db.execute(
            update(JobRun)
            .where(JobRun.status == "running", JobRun.heartbeat_at < cutoff)
            .values(
                status="interrupted",
                finished_at=_now(),
                error="The worker running this job stopped. Start it again.",
            )
        ).rowcount
        db.commit()
    if count:
        logger.warning("marked %d stale run(s) interrupted", count)
    return count or 0


def _beat(run_id: str, worker: str, progress: Optional[Dict[str, Any]]) -> bool:
    """Refresh the heartbeat (and progress); True when a cancel was requested.

    Conditional on still owning the run: a run reaped or cancelled meanwhile is
    left alone.
    """
    values: Dict[str, Any] = {"heartbeat_at": _now()}
    if progress is not None:
        values["progress"] = progress
    with get_scoped_db() as db:
        db.execute(
            update(JobRun)
            .where(
                JobRun.id == run_id,
                JobRun.claimed_by == worker,
                JobRun.status == "running",
            )
            .values(**values)
        )
        db.commit()
        row = db.get(JobRun, run_id)
        return bool(row is None or row.cancel_requested or row.status != "running")


def _finish(run_id: str, worker: str, **fields: Any) -> None:
    with get_scoped_db() as db:
        db.execute(
            update(JobRun)
            .where(
                JobRun.id == run_id,
                JobRun.claimed_by == worker,
                JobRun.status == "running",
            )
            .values(finished_at=_now(), **fields)
        )
        db.commit()


async def execute(run_id: str, worker: str) -> str:
    """Run one claimed run to its end; returns the final status."""
    from server.services.credentials import resolve_credentials

    with get_scoped_db() as db:
        row = db.get(JobRun, run_id)
        assert row is not None
        owner_id, job_id = row.owner_id, row.job_id
        options, model_ref = dict(row.options or {}), row.model_ref

    spec = JOBS.get(job_id)
    if spec is None:
        _finish(run_id, worker, status="failed", error=f"Unknown job '{job_id}'")
        return "failed"

    latest: Dict[str, Any] = {"value": None}

    def progress(done: int, total: int, label: str) -> None:
        latest["value"] = {"done": done, "total": total, "label": label}

    async def work():
        # The owner's own keys, read now — never carried in the queue row.
        creds = await asyncio.to_thread(resolve_credentials, owner_id)
        parsed = spec.options.model_validate(options)
        return await spec.runner(creds, parsed, model_ref, progress)

    task = asyncio.create_task(work())
    beat_every = min(2.0, config.worker_heartbeat_seconds)
    while not task.done():
        await asyncio.wait({task}, timeout=beat_every)
        if task.done():
            break
        pending, latest["value"] = latest["value"], None
        if await asyncio.to_thread(_beat, run_id, worker, pending):
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 — cancellation is the point
                pass
            _finish(run_id, worker, status="cancelled", progress=None)
            return "cancelled"

    try:
        outcome = task.result()
    except Exception as exc:  # noqa: BLE001 — recorded on the run, shown on the page
        logger.exception("Job %s run %s failed", job_id, run_id)
        _finish(run_id, worker, status="failed", error=redact(str(exc)), progress=None)
        return "failed"
    _finish(
        run_id,
        worker,
        status="succeeded",
        result=outcome.result.model_dump(mode="json"),
        draft=outcome.draft,
        progress=None,
        published_url=None if outcome.draft else outcome.result.url,
        published_at=None if outcome.draft or not outcome.result.url else _now(),
    )
    return "succeeded"


async def run_once(worker: Optional[str] = None) -> Optional[str]:
    """Claim and execute one run, if any (tests, and the worker loop's step)."""
    worker = worker or worker_name()
    run_id = await asyncio.to_thread(claim_next, worker)
    if run_id is None:
        return None
    await execute(run_id, worker)
    return run_id


async def run_forever(stop: asyncio.Event, concurrency: Optional[int] = None) -> None:
    """The worker loop: sweep stale runs, claim, execute — until ``stop`` is set,
    then drain the runs in progress for ``WORKER_DRAIN_SECONDS``."""
    worker = worker_name()
    slots = concurrency or config.worker_concurrency
    running: set[asyncio.Task] = set()
    logger.info("worker %s started (%d slot(s))", worker, slots)
    last_sweep = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        if loop.time() - last_sweep > config.worker_heartbeat_seconds:
            await asyncio.to_thread(reap_stale)
            last_sweep = loop.time()
        claimed = None
        if len(running) < slots:
            try:
                claimed = await asyncio.to_thread(claim_next, worker)
            except Exception as exc:  # noqa: BLE001 — DB blip: retry next tick
                logger.warning("claim failed: %s", exc)
        if claimed:
            task = asyncio.create_task(execute(claimed, worker))
            running.add(task)
            task.add_done_callback(running.discard)
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.worker_poll_seconds)
        except asyncio.TimeoutError:
            pass
    if running:
        logger.info("draining %d run(s)…", len(running))
        await asyncio.wait(running, timeout=config.worker_drain_seconds)
    logger.info("worker %s stopped", worker)
