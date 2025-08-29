import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse
import re

from app.core.config import config
from app.models.scraping import ScrapedContent

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
    
    def _generate_item_id(self, item: Dict) -> str:
        """Generate a unique ID based on the hash of the item's content."""
        content_str = json.dumps(item, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()[:16]
    
    def prepare_for_langfuse(self, items: List[Dict], dataset_name: str) -> List[Dict]:
        """Prepare items of the dataset for Langfuse and add IDs and metada."""
        prepared_items = []
        for item in items:
            # Copy item to don't modify the original
            prepared_item = item.copy()
            # Add a unique ID if don't exist
            if "id" not in prepared_item:
                prepared_item["id"] = self._generate_item_id(item)
            prepared_items.append(prepared_item)
        
        return prepared_items

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
    
    def save_dataset(self, 
                     data, 
                     formats: List[str] = None, 
                     prefix: str = None,
                     dataset_name: Optional[str] = None,
                     sub_category: Optional[str] = None) -> List[Path]:
        """
        Save a dataset in JSON format with standardized naming.

        Args:
            data: Dictionary with categories or List of items
            formats: Ignored, only JSON is used
            prefix: Ignored, using standardized naming
            dataset_name: Name of the dataset (category)
            sub_category: Sub-category for the dataset

        Returns:
            List of paths to the created files
        """
        ts = self._get_timestamp()
        paths = []
        
        # Convert list to dict structure if needed
        if isinstance(data, list):
            category_name = dataset_name or "general"
            items_dict = {
                category_name: {
                    f"qa_{i}": item for i, item in enumerate(data)
                }
            }
        else:
            items_dict = data
        
        # Create base directory
        base_dir = self.datasets_dir / "qa"
        base_dir.mkdir(parents=True, exist_ok=True)
        
        # Process each category
        for category_name, category_items in items_dict.items():
            # Use provided sub_category or default to 'data'
            current_sub_category = sub_category or "data"
            
            # Prepare items for Langfuse format
            prepared_items = []
            for item_key, item_data in category_items.items():
                prepared_item = item_data.copy()
                if "id" not in prepared_item:
                    prepared_item["id"] = self._generate_item_id(item_data)
                prepared_items.append(prepared_item)
            
            # Save only in JSON format with standardized naming
            filename = f"{category_name}-{current_sub_category}-{ts}.json"
            file_path = base_dir / filename
            file_path.write_text(
                json.dumps(prepared_items, ensure_ascii=False, indent=2), 
                encoding="utf-8"
            )
            paths.append(file_path)

        return paths