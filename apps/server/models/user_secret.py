from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class UserSecret(Base):
    """One secret a user entered (an API key or token), encrypted at rest.

    ``ciphertext`` is AES-GCM output bound to ``user_id|kind`` (core/crypto.py),
    ``key_id`` names the ring key that produced it. ``hint`` is the last four
    characters of an API key so the user can tell which one is saved — never set
    for OAuth-style tokens. Nothing here is ever returned by the API.
    """

    __tablename__ = "user_secrets"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(String, nullable=False)
    hint: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class UserSettings(Base):
    """A user's non-secret integration settings (base URL, namespaces, repos…)."""

    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
