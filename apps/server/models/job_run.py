import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class JobRun(Base):
    """One run of a dataset job (server/jobs/registry.py), started from /jobs.

    Runs execute in the background; this row is what the page polls. A job
    that produces a draft (github-personal) keeps it in ``draft`` until the
    user reviews and publishes it — the draft is published as-is, never
    regenerated.

    ``status``: running → succeeded | failed; a succeeded draft → published.
    """

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
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
