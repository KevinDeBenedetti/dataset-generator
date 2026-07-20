from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class QAItem(BaseModel):
    """Model for an individual Q&A item"""

    id: str = Field(..., description="Unique ID of the question-answer")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Answer")
    context: str = Field(..., description="Source context")
    source_url: Optional[str] = Field(None, description="Source URL")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence level")
    created_at: datetime = Field(..., description="Creation date")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class QAItemDetailed(QAItem):
    """Model for a Q&A item with full details"""

    updated_at: Optional[datetime] = Field(None, description="Last modification date")
    dataset: Optional[Dict[str, Optional[str]]] = Field(
        None, description="Associated dataset information"
    )


class QAListResponse(BaseModel):
    """Response model for a dataset's Q&A list"""

    dataset_name: str = Field(..., description="Dataset name")
    dataset_id: str = Field(..., description="Dataset ID")
    total_count: int = Field(..., description="Total number of items")
    returned_count: int = Field(..., description="Number of items returned")
    offset: int = Field(0, description="Applied offset")
    limit: Optional[int] = Field(None, description="Applied limit")
    qa_data: List[QAItem] = Field(..., description="List of question-answers")


class QAScoreBucket(BaseModel):
    """One bucket of the confidence-score distribution"""

    label: str = Field(..., description="Human-readable bucket range, e.g. '0.9–1.0'")
    count: int = Field(..., ge=0, description="Number of scored items in the bucket")


class QAStatsResponse(BaseModel):
    """Aggregated confidence-score statistics over a whole dataset.

    Computed server-side over every active item so the quality page doesn't
    have to sample a capped page of Q&A items client-side.
    """

    dataset_name: str = Field(..., description="Dataset name")
    dataset_id: str = Field(..., description="Dataset ID")
    total_count: int = Field(..., description="Total number of active items")
    scored_count: int = Field(
        ..., description="Items carrying a confidence score (the stats basis)"
    )
    average_score: Optional[float] = Field(
        None, description="Mean confidence of scored items (null when none)"
    )
    score_threshold: float = Field(..., description="Threshold used for the split")
    below_threshold_count: int = Field(
        ..., description="Scored items strictly below the threshold"
    )
    validated_count: int = Field(
        ..., description="Scored items at or above the threshold"
    )
    distribution: List[QAScoreBucket] = Field(
        ..., description="Score distribution buckets, highest range first"
    )
