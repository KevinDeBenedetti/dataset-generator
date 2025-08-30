from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from dataclasses import dataclass, field as dc_field
import time

class UrlEntry(BaseModel):
    """An individual URL entry with its description"""
    url: str = Field(..., description="URL to scrape")
    description: Optional[str] = Field(None, description="Source description")

class UrlsConfig(BaseModel):
    """Configuration of URLs with flexible hierarchical structure"""
    # Uses a generic Dict to accept any structure
    model_config = {"extra": "allow"}
    
    def __init__(self, **data):
        # Allows initialization with any structure
        super().__init__(**data)
        # Stores the data in an accessible attribute
        for key, value in data.items():
            setattr(self, key, value)

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

@dataclass
class ScrapedContent:
    url: str
    text: str
    user_agent: str
    timestamp: str

@dataclass
class ScrapingMetrics:
    urls_processed: int = 0
    qa_pairs_generated: int = 0
    errors: List[str] = dc_field(default_factory=list)
    start_time: float = dc_field(default_factory=time.time)
    duration: float = 0.0
    rate: float = 0.0
    _start_time: Optional[float] = None
    _end_time: Optional[float] = None
    
    def add_error(self, error: str):
        from datetime import datetime
        self.errors.append(f"{datetime.now().isoformat()}: {error}")
    
    def get_summary(self) -> str:
        self.calculate_rate()
        return f"""
Scraping Summary:
- URLs processed: {self.urls_processed}
- QA pairs generated: {self.qa_pairs_generated}
- Errors: {len(self.errors)}
- Duration: {self.duration:.2f}s
- Rate: {self.rate:.2f} QA/s
        """
    
    def start_timer(self):
        self._start_time = time.time()

    def stop_timer(self):
        self._end_time = time.time()
        if self._start_time is not None:
            self.duration = self._end_time - self._start_time

    def calculate_rate(self):
        if self.duration > 0:
            self.rate = self.urls_processed / self.duration
        else:
            self.rate = 0.0