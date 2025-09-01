from dataclasses import dataclass, field
from typing import List, Dict
import os
from dotenv import load_dotenv
import logging

load_dotenv()

def parse_list_env(env_var: str, default: List[str] = None) -> List[str]:
    """Parse a comma-separated environment variable into a list."""
    value = os.getenv(env_var)
    if not value:
        return default or []
    return [item.strip() for item in value.split(',')]

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
    
    # Available LLMs
    available_models: List[str] = field(
        default_factory=lambda: parse_list_env(
            "AVAILABLE_LLMS", 
            ["mistral-small-3.1-24b-instruct-2503", "gpt-4-0613", "gpt-3.5-turbo-1106"]
        )
    )

    # Defaults for runtime overrides (set via route)
    target_language: str = field(
        default_factory=lambda: os.getenv("DEFAULT_TARGET_LANGUAGE", "fr")
    )
    model_cleaning: str = field(
        default_factory=lambda: os.getenv("DEFAULT_CLEANING_MODEL", "mistral-small-3.1-24b-instruct-2503")
    )
    model_qa: str = field(
        default_factory=lambda: os.getenv("DEFAULT_QA_MODEL", "mistral-small-3.1-24b-instruct-2503")
    )
    
    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")
        
        # Ensure default models are in available models
        if self.model_cleaning not in self.available_models:
            self.available_models.append(self.model_cleaning)
        if self.model_qa not in self.available_models:
            self.available_models.append(self.model_qa)

config = Config()