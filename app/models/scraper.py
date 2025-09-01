import uuid
from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.services.database import Base

class PageSnapshot(Base):
    __tablename__ = "page_snapshots"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(String, nullable=False)
    user_agent = Column(String, nullable=False)
    retrieved_at = Column(DateTime, nullable=False)
    content = Column(Text, nullable=False)
    url_hash = Column(String, nullable=False, index=True)
    dataset_id = Column(String, ForeignKey("datasets.id"), nullable=True)  # Rendre nullable pour éviter problèmes circulaires

    @staticmethod
    def compute_hash_from_url(url: str) -> str:
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()

class CleanedText(Base):
    __tablename__ = "cleaned_text"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    page_snapshot_id = Column(String, ForeignKey("page_snapshots.id"), nullable=False)
    content = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    model = Column(String, nullable=False)
