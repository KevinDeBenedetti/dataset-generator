from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, List, Optional, Any, Union

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