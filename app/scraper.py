import requests
import re
import time
import logging
from scrapy import Selector
from fake_useragent import UserAgent
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import config
from app.core.cache import URLCache
from app.models.qa import ScrapedContent
from datetime import datetime, timezone

class WebScraper:
    """Web scraper with caching and error handling capabilities"""
    
    def __init__(self, use_cache: bool = True):
        self.cache = URLCache(config.cache_dir) if use_cache else None
    
    def _setup_session(self) -> requests.Session:
        """Setup requests session with retry strategy"""
        session = requests.Session()
        retries = Retry(
            total=config.max_retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"])
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        return session
    
    def _get_user_agent(self) -> str:
        """Get a random user agent string"""
        try:
            ua = UserAgent()
            return ua.random
        except Exception as e:
            logging.warning(f"fake-useragent failed, using fallback: {e}")
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def _extract_text(self, html: str) -> str:
        """Extract clean text from HTML content"""
        # Clean HTML
        cleaned_html = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', html)
        cleaned_html = re.sub(r'<!--.*?-->', '', cleaned_html, flags=re.S)
        
        # Extract text
        selector = Selector(text=cleaned_html)
        text = ' '.join(selector.xpath('//body//text()').getall())
        return re.sub(r'\s+', ' ', text).strip()
    
    def scrape_url(self, url: str) -> ScrapedContent:
        """Scrape content from a URL with caching support"""
        # Check cache
        if self.cache:
            cached = self.cache.get(url)
            if cached:
                logging.info(f"Using cached data for {url}")
                text, user_agent = cached
                return ScrapedContent(
                    url=url,
                    text=text,
                    user_agent=user_agent,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
        
        # Scrape
        session = self._setup_session()
        user_agent = self._get_user_agent()
        headers = {"User-Agent": user_agent}
        
        logging.info(f"Scraping {url}")
        
        try:
            response = session.get(url, headers=headers, timeout=config.timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"Error scraping {url}: {e}")
            raise
        
        text = self._extract_text(response.text)
        
        # Cache
        if self.cache:
            self.cache.set(url, (text, user_agent))
        
        time.sleep(config.scrape_delay)
        
        return ScrapedContent(
            url=url,
            text=text,
            user_agent=user_agent,
            timestamp=datetime.now(timezone.utc).isoformat()
        )