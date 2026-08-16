from typing import List, Optional

from pydantic import BaseModel, Field


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


class CollectionSearchRequest(BaseModel):
    """Semantic search over a dataset's Qdrant collection."""

    query: str = Field(..., min_length=1, description="Natural-language query")
    limit: int = Field(default=10, ge=1, le=100, description="Max number of hits")
    score_threshold: Optional[float] = Field(
        default=None, description="Minimum similarity score (0–1) to include a hit"
    )


class CollectionSearchResult(BaseModel):
    qa_id: Optional[str] = None
    question: str
    answer: str
    context: str
    source_url: Optional[str] = None
    confidence: Optional[float] = None
    score: Optional[float] = None


class CollectionSearchResponse(BaseModel):
    dataset_name: str
    collection_name: str
    query: str
    count: int
    results: List[CollectionSearchResult]
