from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, List, Optional, Any


class UrlEntry(BaseModel):
    """An individual URL entry with its description"""
    url: HttpUrl = Field(..., description="URL to scrape")
    description: Optional[str] = Field(None, description="Source description")


class ScrapingTask(BaseModel):
    """Scraping task with hierarchical structure like in urls.json"""
    urls_config: Dict[str, Any] = Field(
        ...,
        description="URL configuration with hierarchical structure"
    )
    use_cache: bool = Field(
        True, 
        description="Use cache for already scraped URLs"
    )
    target_language: Optional[str] = Field(
        None, 
        description="Target language for QA (default: en)"
    )


class SimpleUrlList(BaseModel):
    """Simplified format for a list of URLs to scrape"""
    urls: List[str] = Field(..., description="Simple list of URLs to scrape")
    category: str = Field("general", description="Category for all URLs")
    use_cache: bool = Field(True, description="Use cache")


class ScrapingResult(BaseModel):
    """Result of a scraping task"""
    task_id: str = Field(..., description="Unique task ID")
    status: str = Field(..., description="Status: success, error, processing")
    urls_processed: int = Field(0, description="Number of URLs processed")
    qa_pairs_generated: int = Field(0, description="Number of QA pairs generated")
    files_generated: List[str] = Field([], description="Paths of generated files")
    errors: List[str] = Field([], description="Possible errors")
    
    
class TaskStatus(BaseModel):
    """Status of a task"""
    task_id: str
    status: str
    progress: float = Field(0.0, description="Progress from 0 to 1")
    details: Optional[ScrapingResult] = None
    message: Optional[str] = None
