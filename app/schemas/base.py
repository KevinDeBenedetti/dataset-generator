from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime

class PageSnapshotBase(BaseModel):
    url: HttpUrl
    user_agent: Optional[str] = None
    content: str

class PageSnapshotCreate(PageSnapshotBase):
    pass

class PageSnapshotResponse(PageSnapshotBase):
    id: int
    retrieved_at: datetime

    class Config:
        from_attributes = True