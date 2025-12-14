import uuid
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from server.core.database import Base


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(String, nullable=False)
    user_agent = Column(String, nullable=False)
    retrieved_at = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    url_hash = Column(String, nullable=False, index=True)
    dataset_id = Column(
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

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    page_snapshot_id = Column(
        String, ForeignKey("page_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    content = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    model = Column(String, nullable=False)

    # Relations
    page_snapshot = relationship("PageSnapshot", back_populates="cleaned_texts")
