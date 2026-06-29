from pydantic import BaseModel, Field, HttpUrl, ConfigDict
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


class DatasetGenerationRequest(BaseModel):
    """Model for dataset generation request"""

    url: HttpUrl = Field(..., description="URL to process to generate the dataset")
    dataset_name: str = Field(..., description="Name of the dataset to create")
    model_cleaning: Optional[str] = Field(
        None, description="Model to use for text cleaning"
    )
    target_language: Optional[str] = Field(
        None, description="Target language for QA generation"
    )
    model_qa: Optional[str] = Field(None, description="Model to use for QA generation")
    similarity_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Similarity threshold to detect duplicates (0.0-1.0)",
    )
    crawl: bool = Field(
        default=True,
        description="Explore the whole site (follow same-domain internal links) "
        "instead of scraping only the seed URL",
    )
    max_depth: Optional[int] = Field(
        default=None,
        ge=0,
        description="Max link-following depth when crawling (defaults to config)",
    )
    max_pages: Optional[int] = Field(
        default=None,
        ge=1,
        description="Max number of pages to crawl (defaults to config)",
    )
    crawl_delay_seconds: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Throttle: seconds to pause between page fetches while "
        "crawling (0 = no throttle; defaults to config)",
    )
    max_pages_per_domain: Optional[int] = Field(
        default=None,
        ge=0,
        description="Per-domain page budget while crawling (0 = unlimited; "
        "defaults to config)",
    )
    sync_langfuse: bool = Field(
        default=True,
        description="Create/version the dataset in Langfuse at generation time",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/document.pdf",
                "dataset_name": "my_dataset",
                "model_cleaning": "gpt-3.5-turbo",
                "target_language": "en",
                "model_qa": "gpt-4",
                "similarity_threshold": 0.9,
            }
        }
    )


class GitHubGenerationRequest(BaseModel):
    """Model for generating a dataset from a GitHub account's public docs."""

    github_username: str = Field(
        ..., description="GitHub account whose public repos will be mined"
    )
    github_token: Optional[str] = Field(
        None,
        description="Optional token — only used to raise the API rate limit; "
        "only public information is read",
    )
    dataset_name: str = Field(..., description="Name of the dataset to create")
    model_cleaning: Optional[str] = Field(
        None, description="Model to use for text cleaning"
    )
    target_language: Optional[str] = Field(
        None, description="Target language for QA generation"
    )
    model_qa: Optional[str] = Field(None, description="Model to use for QA generation")
    similarity_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Similarity threshold to detect duplicates (0.0-1.0)",
    )
    max_repos: Optional[int] = Field(
        default=None,
        ge=1,
        description="Cap on the number of public repos to mine (default: all)",
    )
    sync_langfuse: bool = Field(
        default=True,
        description="Create/version the dataset in Langfuse at generation time",
    )


class DatasetGenerationResponse(BaseModel):
    """Model for dataset generation response"""

    id: str = Field(..., description="ID of the dataset")
    qa_pairs: List[QAPair] = Field(
        ..., description="List of generated question-answer pairs"
    )
    dataset_name: str = Field(..., description="Name of the dataset")
    model_cleaning: str = Field(..., description="Model used for text cleaning")
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
        None, description="Raw markdown scraped from the source URL(s)"
    )
    langfuse: Optional[dict] = Field(
        None,
        description="Langfuse versioning summary (dataset name, version, run) "
        "when synced at generation time",
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
                "similarity_threshold": 0.9,
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
