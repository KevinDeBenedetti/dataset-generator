from pydantic import BaseModel, Field, field_validator, HttpUrl
from typing import List, Optional, Literal, Union, Annotated
from enum import Enum
from datetime import datetime
from utils.config import config

# Verify next code
class TargetLanguage(str, Enum):
    fr = "fr"
    en = "en"
    es = "es"
    
# Instead of creating an Enum dynamically, let's create a str Enum class
class ModelName(str, Enum):
    pass

# Then extend it dynamically
for model in config.available_models:
    model_attr = model.replace('-', '_')
    setattr(ModelName, model_attr, model)

# Ensure that ModelName has at least one attribute to be a valid Enum
if not ModelName.__members__:
    setattr(ModelName, "default_model", "default-model")

class DatasetResult(BaseModel):
    """Task Result of a scraping task"""
    task_id: str = Field(..., description="Unique ID of the task")
    status: str = Field(..., description="Status: success, error, processing")
    urls_processed: int = Field(0, description="Number of URLs processed")
    qa_pairs_generated: int = Field(0, description="Number of QA pairs generated")
    files_generated: List[str] = Field([], description="Paths of generated files")
    errors: List[str] = Field([], description="Potential errors")
    duration: float = Field(0.0, description="Duration of the task in seconds")
    rate: float = Field(0.0, description="QA generation rate (QA/s)")

class QA(BaseModel):
    """Item representing a question-answer pair"""
    question: str = Field(..., min_length=10, max_length=500, description="Question related to the context")
    answer: str = Field(..., min_length=20, description="Complete answer based on the context")
    context: str = Field(..., min_length=50, description="Source text that enabled the answer")
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    
    @field_validator('question')
    @classmethod
    def validate_question(cls, v):
        v = v.strip()
        if not v.endswith('?'):
            v = v + '?'
        return v
    
    @field_validator('answer', 'context')
    @classmethod
    def validate_text_fields(cls, v):
        return v.strip()
