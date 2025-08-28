from dataclasses import dataclass, field
from typing import List, Dict
import os
import json
from dotenv import load_dotenv

load_dotenv()

@dataclass
class ScraperConfig:
    # API Configuration
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL"))
    
    # Models
    model_cleaning: str = "mistral-small-3.1-24b-instruct-2503"
    model_qa: str = "mistral-small-3.1-24b-instruct-2503"
    
    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2
    
    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0
    
    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"
    cache_dir: str = "cache"
    target_language: str = field(default_factory=lambda: os.getenv("TARGET_LANGUAGE", "en"))

    # URLs to process (populated from .env)
    urls: List[str] = field(default_factory=list)
    urls_by_category: Dict[str, Dict] = field(default_factory=dict)

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")
        
        urls_source = os.getenv("URLS")

        if urls_source and urls_source.endswith('.json'):
            try:
                with open(urls_source, "r", encoding="utf-8") as f:
                    self.urls_by_category = json.load(f)

                for category, items in self.urls_by_category.items():
                    for item_name, item_data in items.items():
                        if "url" in item_data:
                            self.urls.append(item_data["url"])
            except Exception as e:
                raise EnvironmentError(f"Unable to read URLS_FILE '{urls_source}': {e}")
        elif urls_source:
            self.urls = _parse_urls(urls_source)

def _parse_urls(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    # JSON array
    if raw.startswith("[") and raw.endswith("]"):
        try:
            items = json.loads(raw)
            return [u.strip() for u in items if isinstance(u, str) and u.strip()]
        except Exception:
            pass
    # multiple lines
    if "\n" in raw:
        return [u.strip() for u in raw.splitlines() if u.strip()]
    # common separators
    for sep in (";", ","):
        if sep in raw:
            return [u.strip() for u in raw.split(sep) if u.strip()]
    return [raw]

config = ScraperConfig()