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


class QAResponse(BaseModel):
    """Response model for an individual Q&A"""

    id: str = Field(..., description="Unique ID of the question-answer")
    question: str = Field(..., description="Question")
    answer: str = Field(..., description="Answer")
    context: str = Field(..., description="Source context")
    source_url: Optional[str] = Field(None, description="Source URL")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence level")
    created_at: datetime = Field(..., description="Creation date")
    updated_at: Optional[datetime] = Field(None, description="Last modification date")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    dataset: Optional[Dict[str, Optional[str]]] = Field(
        None, description="Associated dataset information"
    )
