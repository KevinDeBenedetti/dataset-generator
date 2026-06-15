import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.core.database import Base


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    user_agent: Mapped[str] = mapped_column(String, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True
    )

    # Relations
    dataset = relationship("Dataset", back_populates="page_snapshots")
    cleaned_texts = relationship(
        "CleanedText", back_populates="page_snapshot", cascade="all, delete-orphan"
    )

    @staticmethod
    def compute_hash_from_url(url: str) -> str:
        import hashlib

        return hashlib.sha256(url.encode()).hexdigest()


class CleanedText(Base):
    __tablename__ = "cleaned_text"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    page_snapshot_id: Mapped[str] = mapped_column(
        String, ForeignKey("page_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)

    # Relations
    page_snapshot = relationship("PageSnapshot", back_populates="cleaned_texts")
