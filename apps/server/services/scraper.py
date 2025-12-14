import logging
import requests
import re
import time
from scrapy import Selector
from fake_useragent import UserAgent
from sqlalchemy.orm import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone

from server.core.config import config
from server.models.scraper import PageSnapshot, CleanedText


class ScraperService:
    def __init__(self, db: Session):
        self.db = db

    def _setup_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=config.max_retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
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
        cleaned_html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
        cleaned_html = re.sub(r"<!--.*?-->", "", cleaned_html, flags=re.S)

        selector = Selector(text=cleaned_html)
        text = " ".join(selector.xpath("//body//text()").getall())
        return re.sub(r"\s+", " ", text).strip()

    def add_page_snapshot(self, page_snapshot: PageSnapshot) -> None:
        """Adds a new PageSnapshot record to the database"""
        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)

    def scrape_url(self, url: str, dataset_id: int) -> PageSnapshot:
        logging.info(f"Scraping URL: {url}")

        session = self._setup_session()
        user_agent = self._get_user_agent()
        headers = {"User-Agent": user_agent}

        try:
            response = session.get(url, headers=headers, timeout=config.timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"Error scraping {url}: {e}")
            raise

        text = self._extract_text(response.text)
        time.sleep(config.scrape_delay)

        url_hash = PageSnapshot.compute_hash_from_url(url)
        page_snapshot = PageSnapshot(
            url=url,
            user_agent=user_agent,
            content=text,
            retrieved_at=datetime.now(timezone.utc),
            url_hash=url_hash,
            dataset_id=dataset_id,
        )

        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)

        return page_snapshot

    def save_cleaned_text(
        self, page_snapshot_id: int, content: str, language: str, model: str
    ) -> CleanedText:
        """Saves cleaned text to the database"""
        cleaned_text_record = CleanedText(
            page_snapshot_id=page_snapshot_id,
            content=content,
            language=language,
            model=model,
        )

        self.db.add(cleaned_text_record)
        self.db.commit()
        self.db.refresh(cleaned_text_record)

        return cleaned_text_record
