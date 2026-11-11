import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobSchedule(Base):
    """A job's saved options for one user, and when the worker runs it.

    One row per owner, job and ``scope`` — what of the job's the row is about
    (a resume's id for ``resume-qa``; empty for a whole-account job). The
    ``options`` are the run's (jobs/registry.py); ``every`` is ``day``,
    ``week`` or ``month`` at ``at_hour``:``at_minute`` UTC, or null when the
    options are only kept for the runs the user starts. ``next_run_at`` is
    when the worker queues the next run (services/schedules.py): claiming it
    moves the date on, so two workers never queue the same tick.
    """

    __tablename__ = "job_schedules"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "job_id", "scope", name="uq_job_schedules_owner_job_scope"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    owner_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="")
    options: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # "<provider>:<model>"; null = the owner's LLM when the run is queued.
    model_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    every: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    at_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text("3")
    )
    at_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # A scheduled run publishes what passes the checks and keeps the rest for
    # review; off, it stops at a draft like a run the user starts.
    publish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    last_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )
