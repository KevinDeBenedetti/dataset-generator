import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field

class PageSnapShot(SQLModel, table=True):
    __tablename__ = "page_snapshots"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    url: str
    user_agent: str
    retrieved_at: datetime
    content: str
    url_hash: str = Field(index=True)

    @staticmethod
    def compute_hash_from_url(url: str) -> str:
        import hashlib
        return hashlib.sha256(url.encode()).hexdigest()