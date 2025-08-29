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

    # URLs configuration
    _urls_config: Dict = field(default_factory=dict, init=False)
    _urls_list: List[str] = field(default_factory=list, init=False)

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")

        # Load URLs configuration
        self._load_urls_config()
        
    def _load_urls_config(self):
        """Load URLs configuration from environment or file"""
        urls_source = os.getenv("URLS")

        if urls_source and urls_source.endswith('.json'):
            try:
                urls_path = Path(urls_source)
                if not urls_path.exists():
                    raise FileNotFoundError(f"URLs file not found: {urls_path}")
                
                with urls_path.open("r", encoding="utf-8") as f:
                    self._urls_config = json.load(f)
                
                # Extract flat list for backward compatibility
                self._urls_list = self._extract_urls_from_config(self._urls_config)
                
            except Exception as e:
                raise EnvironmentError(f"Unable to read URLs file '{urls_source}': {e}")
        elif urls_source:
            # Legacy: direct URLs string
            self._urls_list = _parse_urls(urls_source)
            self._urls_config = {}

    def _extract_urls_from_config(self, data: Dict) -> List[str]:
        """Extract all URLs from the hierarchical configuration"""
        urls = []
        for value in data.values():
            if isinstance(value, dict):
                if "url" in value:
                    urls.append(value["url"])
                else:
                    urls.extend(self._extract_urls_from_config(value))
        return urls


    @property
    def urls_config(self) -> Dict:
        """Get the complete URLs configuration with hierarchy"""
        return self._urls_config
    
    @property
    def urls(self) -> List[str]:
        """Get flat list of URLs (backward compatibility)"""
        return self._urls_list
    
def _parse_urls(raw: str) -> List[str]:
    """Parse URLs from various string formats"""
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

config = Config()