from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QAItem(BaseModel):
    """Model for an individual Q&A item"""

    id: str = Field(..., description="Unique ID of the question-answer")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Answer")
    context: str = Field(..., description="Source context")
    source_url: str | None = Field(None, description="Source URL")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence level")
    created_at: datetime = Field(..., description="Creation date")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class QAItemDetailed(QAItem):
    """Model for a Q&A item with full details"""

    updated_at: datetime | None = Field(None, description="Last modification date")
    dataset: dict[str, str | None] | None = Field(
        None, description="Associated dataset information"
    )


class QAListResponse(BaseModel):
    """Response model for a dataset's Q&A list"""

    dataset_name: str = Field(..., description="Dataset name")
    dataset_id: str = Field(..., description="Dataset ID")
    total_count: int = Field(..., description="Total number of items")
    returned_count: int = Field(..., description="Number of items returned")
    offset: int = Field(0, description="Applied offset")
    limit: int | None = Field(None, description="Applied limit")
    qa_data: list[QAItem] = Field(..., description="List of question-answers")


class QAResponse(BaseModel):
    """Response model for an individual Q&A"""

    id: str = Field(..., description="Unique ID of the question-answer")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Answer")
    context: str = Field(..., description="Source context")
    source_url: str | None = Field(None, description="Source URL")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence level")
    created_at: datetime = Field(..., description="Creation date")
    updated_at: datetime | None = Field(None, description="Last modification date")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")
    dataset: dict[str, str | None] | None = Field(
        None, description="Associated dataset information"
    )


class UnitQuestionAnswer(BaseModel):
    question: str = Field(..., description="The generated question")
    answer: str = Field(..., description="The generated answer")
    context: str = Field(
        ..., description="The context from which the question was generated"
    )
    confidence: float = Field(
        ...,
        description="The confidence score of the generated answer 0-1",
        ge=0.0,
        le=1.0,
    )


class UnitQuestionAnswerResponse(UnitQuestionAnswer):
    file_id: str
    dataset_id: str
    human_reviewed: bool = Field(
        False, description="Indicates if the Q&A has been human reviewed"
    )
