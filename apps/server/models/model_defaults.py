from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class ModelDefault(Base):
    """The LLM one user's steps run on when a request names none — set on /models.

    One row per user, role ``llm`` (the per-step roles were folded into it by
    migration 5d6e7f8091a2); ``model_ref`` is a ``"<provider>:<model>"``
    reference (see services/providers). A user with no row falls back to
    OPENAI_LLM_MODEL (services/model_defaults.py).
    """

    __tablename__ = "model_defaults"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String, primary_key=True)
    model_ref: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(timezone.utc)
    )
