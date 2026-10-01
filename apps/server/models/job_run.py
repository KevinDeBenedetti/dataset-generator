import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class JobRun(Base):
    """One run of a dataset job (server/jobs/registry.py), started from /jobs.

    The row *is* the queue entry: the API inserts it ``queued``, a worker
    (``python -m server.worker``) claims it, runs it and records the outcome;
    the page polls the row. A job that produces a draft (github-personal) keeps
    it in ``draft`` until the user reviews and publishes it — the draft is
    published as-is, never regenerated.

    ``status``: queued → running → succeeded | failed | cancelled |
    interrupted (its worker stopped heart-beating); a succeeded draft →
    published. A queued run can also go straight to cancelled.
    """

    __tablename__ = "job_runs"
    # At most one active (queued or running) run per user and job, enforced by
    # the database: a check-then-insert is a race between two requests or pods.
    __table_args__ = (
        Index(
            "uq_job_runs_one_active",
            "owner_id",
            "job_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Whose run it is: only the owner can read, publish or list it.
    owner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", index=True
    )
    options: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    model_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # JobResult (dry_run, url, metrics, errors) once the run has finished.
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # The job's unpublished output, when it produces one.
    draft: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # --- queue bookkeeping (services/queue.py) ---
    claimed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Refreshed by the worker every few seconds while running; a stale one means
    # the worker died and the run is marked interrupted (never re-run: it may
    # already have spent model quota or published).
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # {"done", "total", "label"} — written by the worker, throttled.
    progress: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
