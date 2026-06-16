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

    # Reasoning models (e.g. gpt-oss) emit a chain-of-thought before the answer.
    # "low" keeps that short so the agent reliably reaches the final JSON.
    # Set OPENAI_REASONING_EFFORT="" to disable for models that reject the param.
    openai_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "low")
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

    # Deep crawl: when enabled, the scraper follows internal links from the seed
    # URL (breadth-first) to cover the whole site and maximise the dataset.
    # Each discovered page triggers a clean + QA generation, so the limits below
    # bound the cost. Same-domain only by default.
    crawl_max_depth: int = field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_DEPTH", "2"))
    )
    crawl_max_pages: int = field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_PAGES", "50"))
    )
    crawl_same_domain: bool = field(
        default_factory=lambda: (
            os.getenv("CRAWL_SAME_DOMAIN", "true").lower() not in ("0", "false", "no")
        )
    )

    # When true (and Langfuse is configured), every generation also creates/updates
    # the dataset in Langfuse and records a versioned dataset run (DVC-like commit).
    langfuse_auto_sync: bool = field(
        default_factory=lambda: (
            os.getenv("LANGFUSE_AUTO_SYNC", "true").lower() not in ("0", "false", "no")
        )
    )

    # crawl4ai service (Docker). The scraper calls this REST API instead of
    # running crawl4ai in-process, keeping the browser stack out of this image.
    crawl4ai_base_url: str = field(
        default_factory=lambda: os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")
    )
    crawl4ai_api_token: str = field(
        default_factory=lambda: os.getenv("CRAWL4AI_API_TOKEN", "")
    )
    # Upper bound (seconds) for a single /md request: the service renders the
    # page in a browser, so this must comfortably exceed the page timeout.
    crawl4ai_timeout: int = field(
        default_factory=lambda: int(os.getenv("CRAWL4AI_TIMEOUT", "120"))
    )

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
