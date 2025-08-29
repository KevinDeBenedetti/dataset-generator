from pydantic import BaseModel, Field, HttpUrl
from typing import Dict, List, Optional, Any, Union


class UrlEntry(BaseModel):
    """An individual URL entry with its description"""
    url: HttpUrl = Field(..., description="URL to scrape")
    description: Optional[str] = Field(None, description="Source description")


class ScrapingTask(BaseModel):
    """Scraping task with hierarchical structure as in urls.json"""
    urls_config: Dict[str, Any] = Field(
        ...,
        description="Configuration of URLs with hierarchical structure"
    )
    use_cache: bool = Field(
        True,
        description="Use cache for already scraped URLs"
    )
    target_language: Optional[str] = Field(
        None,
        description="Target language for QA (default: fr)"
    )


class SimpleUrlList(BaseModel):
    """Simplified format for a list of URLs to scrape"""
    urls: List[str] = Field(..., description="Simple list of URLs to scrape")
    category: str = Field("general", description="Category for all URLs")
    use_cache: bool = Field(True, description="Use cache")
