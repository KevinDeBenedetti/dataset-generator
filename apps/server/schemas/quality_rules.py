from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class QualityRulesResponse(BaseModel):
    """The persisted generation-time quality rules."""

    min_answer_words: int = Field(
        ..., ge=0, description="Minimum answer length in words (0 = no minimum)"
    )
    reject_below_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence below which pairs are rejected"
    )
    auto_reject_enabled: bool = Field(
        ..., description="Whether the rules are applied at generation"
    )
    updated_at: Optional[datetime] = Field(None, description="Last modification")


class QualityRulesUpdate(BaseModel):
    """Partial update — only the provided fields change."""

    min_answer_words: Optional[int] = Field(None, ge=0)
    reject_below_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    auto_reject_enabled: Optional[bool] = None
