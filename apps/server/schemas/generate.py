from pydantic import BaseModel, Field, ConfigDict

from server.schemas.recipes import HF_REPO_PATTERN
from typing import List, Optional


class QAPair(BaseModel):
    """Model for a question-answer pair"""

    question: str = Field(..., description="Generated question")
    answer: str = Field(..., description="Corresponding answer")


class PipelineStep(BaseModel):
    """One step of the generation pipeline, for the frontend timeline."""

    key: str = Field(..., description="Stable identifier of the step")
    label: str = Field(..., description="Human-readable step name")
    status: str = Field(
        ..., description="Outcome of the step: success, warning or error"
    )
    duration_ms: int = Field(..., description="Step duration in milliseconds")
    detail: str = Field("", description="Log line summarising what happened")


class UrlGenerationRequest(BaseModel):
    """Generate a dataset from one web page (no crawling)."""

    url: str = Field(
        ..., max_length=2048, description="http(s) URL of the page to mine"
    )
    dataset_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the dataset to create or extend",
    )
    target_language: Optional[str] = Field(
        None, description="Target language for QA generation"
    )
    model: Optional[str] = Field(
        None,
        max_length=200,
        description='Model reference, e.g. "openai:chat-default" (default: your LLM)',
    )
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Question similarity at or above which a pair is a duplicate "
        "(0.0-1.0): embedding cosine across the dataset when the embedding model "
        "answers, else a lexical ratio within the same source",
    )
    persist: bool = Field(
        default=True,
        description="Store the generated pairs and record a version at generation time",
    )
    target_repo: Optional[str] = Field(
        None,
        max_length=193,
        pattern=HF_REPO_PATTERN,
        description="Hugging Face dataset to publish to ('namespace/name' or 'name'): "
        "the pairs become a draft to review, not a local dataset",
    )


class DatasetGenerationResponse(BaseModel):
    """Model for dataset generation response"""

    id: str = Field(..., description="ID of the dataset")
    qa_pairs: List[QAPair] = Field(
        ..., description="List of generated question-answer pairs"
    )
    dataset_name: str = Field(..., description="Name of the dataset")
    model: str = Field(..., description="The model of every step")
    target_language: str = Field(..., description="Target language used")
    similarity_threshold: float = Field(..., description="Similarity threshold used")
    total_questions: int = Field(..., description="Total number of generated questions")
    pages_crawled: int = Field(
        default=1, description="Number of pages fetched and processed"
    )
    processing_time: float = Field(..., description="Processing time in seconds")
    steps: List[PipelineStep] = Field(
        default_factory=list, description="Timeline of the pipeline steps"
    )
    scraped_content: Optional[str] = Field(
        None, description="Text extracted from the source, as fed to QA generation"
    )
    persisted: Optional[dict] = Field(
        None,
        description="Summary of the stored version (dataset name, version, run) "
        "when the pairs were saved at generation time",
    )
    draft_run_id: Optional[str] = Field(
        None, description="The draft to review, when a target_repo was given"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "qa_pairs": [
                    {
                        "question": "What is the main topic of this document?",
                        "answer": "The document discusses machine learning techniques.",
                    }
                ],
                "dataset_name": "my_dataset",
                "model": "openai:chat-default",
                "target_language": "en",
                "similarity_threshold": 0.85,
                "total_questions": 50,
                "processing_time": 45.2,
            }
        }
    )


class ErrorResponse(BaseModel):
    """Model for error responses"""

    detail: str = Field(..., description="Detailed error description")
    error_code: Optional[str] = Field(None, description="Specific error code")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Model 'invalid-model' not in available models: ['gpt-3.5-turbo', 'gpt-4']",
                "error_code": "INVALID_MODEL",
            }
        }
    )
