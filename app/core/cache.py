import hashlib
import pickle
import logging
from pathlib import Path
from typing import Optional, Tuple

class URLCache:
    """Simple file-based cache for URL scraping results"""
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
    
    def _get_cache_path(self, url: str) -> Path:
        """Generate cache file path for a given URL"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.pkl"
    
    def get(self, url: str) -> Optional[Tuple[str, str]]:
        """Retrieve cached data for a URL"""
        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logging.warning(f"Cache read error for {url}: {e}")
        return None
    
    def set(self, url: str, data: Tuple[str, str]) -> None:
        """Store data in cache for a URL"""
        cache_path = self._get_cache_path(url)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logging.warning(f"Cache write error for {url}: {e}")
    
    def clear(self) -> None:
        """Clear all cached data"""
        for file in self.cache_dir.glob("*.pkl"):
            file.unlink()