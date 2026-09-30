from pydantic import BaseModel, Field, ConfigDict
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

    url: str = Field(..., description="http(s) URL of the page to mine")
    dataset_name: str = Field(
        ..., description="Name of the dataset to create or extend"
    )
    target_language: Optional[str] = Field(
        None, description="Target language for QA generation"
    )
    model_cleaning: Optional[str] = Field(
        None,
        description='Model reference for text cleaning, e.g. "openai:gpt-4o-mini" '
        "(default: the cleaning role default)",
    )
    model_qa: Optional[str] = Field(
        None,
        description='Model reference for QA generation, e.g. "claude:claude-sonnet-5" '
        "(default: the qa role default)",
    )
    similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Question similarity at or above which a pair is a duplicate "
        "(0.0-1.0): embedding cosine across the dataset when the local model is "
        "available, else a lexical ratio within the same source",
    )
    persist: bool = Field(
        default=True,
        description="Store the generated pairs and record a version at generation time",
    )


class DatasetGenerationResponse(BaseModel):
    """Model for dataset generation response"""

    id: str = Field(..., description="ID of the dataset")
    qa_pairs: List[QAPair] = Field(
        ..., description="List of generated question-answer pairs"
    )
    dataset_name: str = Field(..., description="Name of the dataset")
    model_cleaning: str = Field(
        ..., description="Model used to clean (URL) or transcribe (file) the source"
    )
    target_language: str = Field(..., description="Target language used")
    model_qa: str = Field(..., description="Model used for QA generation")
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
                "model_cleaning": "gpt-3.5-turbo",
                "target_language": "en",
                "model_qa": "gpt-4",
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
