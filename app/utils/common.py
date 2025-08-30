from typing import List, Dict, Any
from urllib.parse import urlparse

from app.models.dataset import QA

def qa_to_dict_list(qa_list: List[QA]) -> List[Dict]:
    """Convert a list of QA to dictionaries"""
    return [qa.model_dump() for qa in qa_list]

def print_summary(metrics, paths: List):
    print("\n" + "="*50)
    print("SCRAPING COMPLETED")
    print("="*50)
    print(metrics.get_summary())
    
    if paths:
        print("\nFiles generated:")
        for path in paths:
            print(f"  - {path}")
    
    if metrics.errors:
        print(f"\nErrors ({len(metrics.errors)}):")
        for error in metrics.errors[-5:]:  # Last 5 errors
            print(f"  - {error}")

def is_valid_url(url: str) -> bool:
    """Basic validation of a URL (scheme + netloc)."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False
    
def flatten_urls(urls_dict: Dict[str, Any]) -> List[tuple[str, str]]:
    """Flatten nested URL structure to list of (dataset_name, url) tuples"""
    result = []
    
    def recursive_flatten(data: Dict[str, Any], path_parts: List[str] = []):
        for key, value in data.items():
            current_path = path_parts + [key]
            
            if isinstance(value, dict):
                if "url" in value:
                    # C'est une UrlEntry
                    dataset_name = "-".join(current_path)
                    result.append((dataset_name, value["url"]))
                else:
                    # Continue la récursion
                    recursive_flatten(value, current_path)
    
    recursive_flatten(urls_dict)
    return result