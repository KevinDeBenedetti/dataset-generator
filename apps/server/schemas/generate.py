from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class QAPair(BaseModel):
    """Model for a question-answer pair"""

    question: str = Field(..., description="Generated question")
    answer: str = Field(..., description="Corresponding answer")


class DatasetGenerationRequest(BaseModel):
    """Model for dataset generation request"""

    url: HttpUrl = Field(..., description="URL to process to generate the dataset")
    dataset_name: str = Field(..., description="Name of the dataset to create")
    model_cleaning: str | None = Field(
        None, description="Model to use for text cleaning"
    )
    target_language: str | None = Field(
        None, description="Target language for QA generation"
    )
    model_qa: str | None = Field(None, description="Model to use for QA generation")
    similarity_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Similarity threshold to detect duplicates (0.0-1.0)",
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


class DatasetGenerationResponse(BaseModel):
    """Model for dataset generation response"""

    id: str = Field(..., description="ID of the dataset")
    qa_pairs: list[QAPair] = Field(
        ..., description="List of generated question-answer pairs"
    )
    dataset_name: str = Field(..., description="Name of the dataset")
    model_cleaning: str = Field(..., description="Model used for text cleaning")
    target_language: str = Field(..., description="Target language used")
    model_qa: str = Field(..., description="Model used for QA generation")
    similarity_threshold: float = Field(..., description="Similarity threshold used")
    total_questions: int = Field(..., description="Total number of generated questions")
    processing_time: float = Field(..., description="Processing time in seconds")

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
    error_code: str | None = Field(None, description="Specific error code")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Model 'invalid-model' not in available models: ['gpt-3.5-turbo', 'gpt-4']",
                "error_code": "INVALID_MODEL",
            }
        }
    )
