import requests
import re
import time
import logging
from scrapy import Selector
from fake_useragent import UserAgent
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Tuple

from app.config import config
from app.cache import URLCache
from app.models import ScrapedContent
from datetime import datetime, timezone

class WebScraper:
    def __init__(self, use_cache: bool = True):
        self.cache = URLCache(config.cache_dir) if use_cache else None
    
    def _setup_session(self) -> requests.Session:
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
        try:
            ua = UserAgent()
            return ua.random
        except Exception as e:
            logging.warning(f"fake-useragent failed, using fallback: {e}")
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    def _extract_text(self, html: str) -> str:
        # Nettoyage HTML
        cleaned_html = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', html)
        cleaned_html = re.sub(r'<!--.*?-->', '', cleaned_html, flags=re.S)
        
        # Extraction texte
        selector = Selector(text=cleaned_html)
        text = ' '.join(selector.xpath('//body//text()').getall())
        return re.sub(r'\s+', ' ', text).strip()
    
    def scrape_url(self, url: str) -> ScrapedContent:
        # Vérifier cache
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
        
        # Scraper
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