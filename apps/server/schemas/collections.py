from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class EmbeddingModelOut(BaseModel):
    name: str = Field(
        ..., description='A local model, or "openai:<id>" for an endpoint one'
    )
    dimensions: Optional[int] = None
    size_mb: Optional[int] = Field(None, description="Download size, roughly")
    languages: str
    description: str
    provider: str = Field(
        "local",
        description='"local" (FastEmbed, on the server) or "openai" '
        "(your OpenAI-compatible endpoint: the rows are sent to it)",
    )


class CollectionProgress(BaseModel):
    done: int = 0
    total: int = 0
    label: str = ""


class CollectionMiss(BaseModel):
    """A sampled row whose own point didn't come back first."""

    row_idx: int
    query: str
    rank: Optional[int] = Field(None, description="Rank of its own point; null past k")
    expected: str = Field(..., description="Its own point's embedded text")
    top_row_idx: Optional[int] = None
    top_score: Optional[float] = None
    top_text: str = ""


class CollectionEvaluation(BaseModel):
    """A retrieval test: sampled rows ask with their query column."""

    query_column: str
    sample: int = Field(..., description="Rows asked for")
    queries: int = Field(..., description="Rows tested: sampled, with a query")
    k: int
    hit_at_1: float = Field(..., description="Share of rows whose point came first")
    hit_at_k: float = Field(
        ..., description="Share of rows whose point was in the top k"
    )
    mrr: float = Field(..., description="Mean reciprocal rank (0 past k)")
    trivial: bool = Field(
        ...,
        description="The query column is embedded too: every row finds itself",
    )
    model: str
    revision: str
    evaluated_at: str
    misses: List[CollectionMiss]


class CollectionOut(BaseModel):
    id: str
    name: str
    repo_id: str
    revision: str = Field(..., description="Commit sha the vectors are built from")
    config: str
    split: str
    text_columns: List[str]
    query_column: Optional[str] = None
    model: str
    status: Literal["building", "ready", "failed"]
    error: Optional[str] = None
    progress: Optional[CollectionProgress] = None
    run_id: Optional[str] = Field(None, description="The latest build's job run")
    vector_size: Optional[int] = None
    rows_total: Optional[int] = Field(None, description="Rows in the split")
    points_count: Optional[int] = Field(
        None, description="Rows embedded (empty ones are skipped)"
    )
    fields: List[str] = Field(
        default_factory=list, description="Columns kept in each point's payload"
    )
    qdrant_collection: str = Field(..., description="The collection's name in Qdrant")
    evaluation: Optional[CollectionEvaluation] = None
    created_at: datetime
    updated_at: datetime
    built_at: Optional[datetime] = None


class CollectionsOut(BaseModel):
    qdrant_configured: bool
    quota: int = Field(..., description="Collections per user (0 = unlimited)")
    models: List[EmbeddingModelOut]
    collections: List[CollectionOut]


class CollectionCreate(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    repo_id: str = Field(..., max_length=200, description="namespace/name on the Hub")
    revision: Optional[str] = Field(
        None, max_length=256, description="Branch, tag or sha; default: latest"
    )
    config: Optional[str] = Field(None, max_length=256)
    split: Optional[str] = Field(None, max_length=512)
    text_columns: List[ColumnName] = Field(
        ..., min_length=1, max_length=4, description="Joined into the embedded text"
    )
    query_column: Optional[ColumnName] = Field(
        None, description="What the retrieval test asks with (the question)"
    )
    model: Optional[str] = Field(None, max_length=200, description="Default: the first")


class CollectionBuildRequest(BaseModel):
    revision: Optional[str] = Field(
        None, max_length=256, description="Branch, tag or sha; default: latest"
    )


class CollectionSearchRequest(BaseModel):
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    limit: int = Field(10, ge=1, le=50)
    score_threshold: Optional[float] = Field(None, ge=-1, le=1)


class CollectionHit(BaseModel):
    row_idx: int = Field(..., description="Position of the row in the split")
    score: float = Field(..., description="Cosine similarity to the query")
    text: str = Field(..., description="The embedded text")
    fields: Dict[str, Any]


class CollectionSearchOut(BaseModel):
    query: str
    took_ms: int
    hits: List[CollectionHit]


class CollectionEvaluateRequest(BaseModel):
    sample: int = Field(100, ge=10, le=500, description="Rows to test")
    k: int = Field(10, ge=1, le=50)
    query_column: Optional[ColumnName] = Field(
        None, description="Default: the collection's query column"
    )
