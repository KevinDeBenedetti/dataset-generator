from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from dataclasses import dataclass, field as dc_field
import time

class QA(BaseModel):
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