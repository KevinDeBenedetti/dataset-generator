from dataclasses import dataclass, field
from typing import List
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # API Configuration (single OpenAI-compatible provider)
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "")
    )

    # Models (one per role, from the configured provider)
    openai_llm_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", "")
    )
    openai_embedding_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_EMBEDDING_MODEL", "")
    )
    openai_vlm_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_VLM_MODEL", "")
    )

    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2

    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0

    # Defaults for runtime overrides (set via route)
    target_language: str = field(
        default_factory=lambda: os.getenv("DEFAULT_TARGET_LANGUAGE", "en")
    )
    model_cleaning: str = field(
        default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", "")
    )
    model_qa: str = field(default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", ""))

    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    # Available models, derived from the configured provider models
    available_models: List[str] = field(default_factory=list)

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")

        # Build the available-models list from every configured model,
        # de-duplicated and preserving order.
        candidates = [
            self.openai_llm_model,
            self.openai_vlm_model,
            self.model_cleaning,
            self.model_qa,
        ]
        self.available_models = list(dict.fromkeys(m for m in candidates if m))


config = Config()
