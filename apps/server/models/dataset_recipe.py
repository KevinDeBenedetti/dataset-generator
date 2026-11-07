import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DatasetRecipe(Base):
    """What a GitHub-fed dataset is generated from, saved per user.

    A recipe names the Hugging Face repo it publishes to and the public GitHub
    sources that feed it: the profile facts, and per repo its README and the
    ``docs/`` files picked on the GitHub page. ``sources`` is a list of
    ``{"repo": str, "readme": bool, "docs": [path, ...] | null}``; ``docs``
    null means the generation's default pick (services/recipes.py).
    """

    __tablename__ = "dataset_recipes"
    # Names are how the user tells recipes apart: unique per owner.
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_dataset_recipes_owner_name"),
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
    name: Mapped[str] = mapped_column(String, nullable=False)
    # "namespace/name", or a bare name completed with the user's namespace.
    target_repo: Mapped[str] = mapped_column(String, nullable=False)
    include_profile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    sources: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # "<provider>:<model>"; null = the jobs role default.
    model_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_now, onupdate=_now
    )
