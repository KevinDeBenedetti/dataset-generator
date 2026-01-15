from enum import Enum

from pydantic import BaseModel, Field, field_validator

from server.core.config import config


class TargetLanguage(str, Enum):
    fr = "fr"
    en = "en"
    es = "es"
    de = "de"


def _build_model_enum() -> Enum:
    """Return a str-based Enum containing configured model names."""
    members = {model.replace("-", "_"): model for model in config.available_models}
    if not members:
        members = {"default_model": "default-model"}
    return Enum("ModelName", members, type=str)


ModelName = _build_model_enum()


class DatasetResult(BaseModel):
    """Task Result of a scraping task"""

    task_id: str = Field(..., description="Unique ID of the task")
    status: str = Field(..., description="Status: success, error, processing")
    urls_processed: int = Field(0, description="Number of URLs processed")
    qa_pairs_generated: int = Field(0, description="Number of QA pairs generated")
    files_generated: list[str] = Field([], description="Paths of generated files")
    errors: list[str] = Field([], description="Potential errors")
    duration: float = Field(0.0, description="Duration of the task in seconds")
    rate: float = Field(0.0, description="QA generation rate (QA/s)")


class QA(BaseModel):
    """Item representing a question-answer pair"""

    question: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Question related to the context",
    )
    answer: str = Field(
        ..., min_length=20, description="Complete answer based on the context"
    )
    context: str = Field(
        ..., min_length=50, description="Source text that enabled the answer"
    )
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("question")
    @classmethod
    def validate_question(cls, v):
        v = v.strip()
        if not v.endswith("?"):
            v = v + "?"
        return v

    @field_validator("answer", "context")
    @classmethod
    def validate_text_fields(cls, v):
        return v.strip()


class DatasetResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    qa_sources_count: int | None = None
    created_at: str | None = None
    message: str | None = None


class SimilarityPair(BaseModel):
    record1_id: str
    record2_id: str
    similarity: float
    question1: str
    question2: str


class SimilarityAnalysisResponse(BaseModel):
    dataset_id: str
    dataset_name: str
    threshold: float
    total_records: int
    similar_pairs_found: int
    similarities: list[SimilarityPair]


class CleanSimilarityPair(BaseModel):
    keep_id: str
    remove_id: str
    similarity: float
    keep_question: str
    remove_question: str


class RemovedRecord(BaseModel):
    id: str
    question: str
    similarity: float
    kept_id: str


class CleanSimilarityResponse(BaseModel):
    dataset_id: str
    dataset_name: str
    threshold: float
    total_records: int
    removed_records: int
    details: list[CleanSimilarityPair]
    removed_items: list[RemovedRecord]


class DeleteDatasetResponse(BaseModel):
    message: str
    dataset_id: str
    records_deleted: int
