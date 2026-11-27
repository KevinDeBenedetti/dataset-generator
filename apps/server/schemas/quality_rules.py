from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TabularRules(BaseModel):
    """The rules of tabular drafts (review/tabular_quality.py)."""

    min_rows: Optional[int] = Field(None, ge=0, description="Fewest rows a draft has")
    max_null_share: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Largest empty share of any column"
    )
    required_columns: List[str] = Field(default_factory=list, max_length=200)
    unmasked_pii: Literal["auto", "block", "warn", "off"] = Field(
        "auto",
        description="Unmasked personal data; auto: block e-mails, phones and NIR "
        "in a public dataset, warn otherwise",
    )
    severity: Literal["warn", "block"] = Field(
        "warn", description="What a failed row, empty-share or column rule does"
    )


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
    tabular: Optional[TabularRules] = Field(
        None, description="Tabular draft rules (null: the defaults)"
    )
    updated_at: Optional[datetime] = Field(None, description="Last modification")


class QualityRulesUpdate(BaseModel):
    """Partial update — only the provided fields change."""

    min_answer_words: Optional[int] = Field(None, ge=0)
    reject_below_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    auto_reject_enabled: Optional[bool] = None
    tabular: Optional[TabularRules] = None
