from typing import List, Optional

from pydantic import BaseModel


class Collection(BaseModel):
    """A dataset projected as a vector collection.

    Carries the dataset fields plus its Qdrant status. ``in_qdrant`` /
    ``points_count`` are null when Qdrant is unconfigured or unreachable.
    """

    id: str
    name: str
    description: Optional[str] = None
    target_language: Optional[str] = None
    qa_sources_count: Optional[int] = None
    created_at: Optional[str] = None
    collection_name: str
    in_qdrant: Optional[bool] = None
    points_count: Optional[int] = None


class CollectionsResponse(BaseModel):
    qdrant_configured: bool
    total: int
    collections: List[Collection]


class QdrantSyncResponse(BaseModel):
    dataset_name: str
    collection_name: str
    points_upserted: int
    vector_size: int
