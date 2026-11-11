from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddingCalibration(Base):
    """The thresholds of the embedding checks, measured for one user's
    embedding model on the built-in test set (services/calibration.py).

    Kept per model: switching back to a model measured before needs no new
    measurement. ``report`` is what the Models page shows of the measurement.
    """

    __tablename__ = "embedding_calibrations"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    model_ref: Mapped[str] = mapped_column(String, primary_key=True)
    dedup: Mapped[float] = mapped_column(Float, nullable=False)
    grounding: Mapped[float] = mapped_column(Float, nullable=False)
    uncovered: Mapped[float] = mapped_column(Float, nullable=False)
    report: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now
    )
