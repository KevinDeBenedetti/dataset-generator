from dataclasses import dataclass, field
from typing import List, Dict
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # API Configuration
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL"))
    
    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2
    
    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0

    # Defaults for runtime overrides (set via route)
    target_language: str = "en"
    model_cleaning: str = "mistral-small-3.1-24b-instruct-2503"
    model_qa: str = "mistral-small-3.1-24b-instruct-2503"
    
    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")

config = Config()