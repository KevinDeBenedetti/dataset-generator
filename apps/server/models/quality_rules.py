from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class QualityRules(Base):
    """One user's generation-time quality rules (one row per user).

    The thresholds shown on the /quality
    page and applied by the generation pipeline when ``auto_reject_enabled``
    is on. Defaults are prefilled with sensible values but enforcement stays
    off until explicitly enabled.
    """

    __tablename__ = "quality_rules"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Minimum answer length, in words (0 = no minimum).
    min_answer_words: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    # Generated pairs below this confidence are rejected.
    reject_below_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.8
    )
    # Master switch: rules are only applied at generation when true.
    auto_reject_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(timezone.utc)
    )
