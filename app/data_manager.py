import json
import csv
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timezone
from urllib.parse import urlparse
import re

from app.config import config
from app.models import ScrapedContent

class DataManager:
    def __init__(self):
        self.scrapes_dir = Path(config.scrapes_dir)
        self.datasets_dir = Path(config.datasets_dir)
        self.scrapes_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
    
    def _slugify_url(self, url: str) -> str:
        parsed = urlparse(url)
        slug = f"{parsed.netloc}{parsed.path}"
        slug = re.sub(r'[^A-Za-z0-9]+', '-', slug).strip('-').lower()
        return slug or "page"
    
    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    def save_markdown(self, content: ScrapedContent) -> Path:
        ts = self._get_timestamp()
        filename = f"{self._slugify_url(content.url)}-{ts}.md"
        path = self.scrapes_dir / filename
        
        md_content = (
            f"# Snapshot: {content.url}\n\n"
            f"> User-Agent: `{content.user_agent}`\n\n"
            f"> Date (UTC): {content.timestamp}\n\n"
            f"---\n\n"
            f"## Extracted text\n\n"
            f"{content.text}\n"
        )
        
        path.write_text(md_content, encoding="utf-8")
        return path
    
    def save_cleaned_text(self, content: ScrapedContent, cleaned_text: str) -> Path:
        ts = self._get_timestamp()
        filename = f"{self._slugify_url(content.url)}-{ts}.txt"
        path = self.datasets_dir / "texts" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        
        header = (
            f"URL: {content.url}\n"
            f"User-Agent: {content.user_agent}\n"
            f"Date (UTC): {content.timestamp}\n"
            f"---\n\n"
        )
        
        path.write_text(header + cleaned_text, encoding="utf-8")
        return path
    
    def save_dataset(self, items: List[Dict], formats: List[str] = None, prefix: str = None) -> List[Path]:
        formats = formats or config.output_formats
        ts = self._get_timestamp()
        prefix = f"{prefix}-" if prefix else ""
        paths = []
        
        qa_dir = self.datasets_dir / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        
        if "json" in formats:
            path = qa_dir / f"{prefix}dataset-{ts}.json"
            path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            paths.append(path)
        
        if "jsonl" in formats:
            path = qa_dir / f"{prefix}dataset-{ts}.jsonl"
            with path.open("w", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            paths.append(path)
        
        if "csv" in formats:
            path = qa_dir / f"{prefix}dataset-{ts}.csv"
            if items:
                all_keys = set()
                for item in items:
                    all_keys.update(item.keys())
                
                preferred = ["question", "answer", "context"]
                rest = sorted(k for k in all_keys if k not in preferred)
                fieldnames = [k for k in preferred if k in all_keys] + rest
                
                with path.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for item in items:
                        row = {k: item.get(k, "") for k in fieldnames}
                        writer.writerow(row)
            paths.append(path)
        
        return paths