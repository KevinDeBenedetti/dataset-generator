from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class ModelDefault(Base):
    """The model a role uses when a request names none — set on /models.

    One row per role (cleaning, qa, vision, jobs); ``model_ref`` is a
    ``"<provider>:<model>"`` reference (see services/providers). A role with
    no row falls back to the environment (services/model_defaults.py).
    """

    __tablename__ = "model_defaults"

    role: Mapped[str] = mapped_column(String, primary_key=True)
    model_ref: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, default=lambda: datetime.now(timezone.utc)
    )
