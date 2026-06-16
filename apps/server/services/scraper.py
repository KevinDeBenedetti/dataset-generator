import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.scraper import PageSnapshot, CleanedText


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ScraperService:
    def __init__(self, db: Session):
        self.db = db

    async def _fetch_markdown(self, url: str) -> str:
        """Fetch a page as Markdown via the crawl4ai service (/md endpoint).

        Uses the ``raw`` filter so the result mirrors crawl4ai's
        ``raw_markdown`` (the cleaning step downstream refines it).
        """
        endpoint = f"{config.crawl4ai_base_url.rstrip('/')}/md"
        headers = {}
        if config.crawl4ai_api_token:
            headers["Authorization"] = f"Bearer {config.crawl4ai_api_token}"

        try:
            async with httpx.AsyncClient(timeout=config.crawl4ai_timeout) as client:
                response = await client.post(
                    endpoint, json={"url": url, "f": "raw"}, headers=headers
                )
        except httpx.HTTPError as e:
            logging.error(f"Error scraping {url}: {e}")
            raise

        if response.status_code != 200:
            detail = response.text or f"HTTP {response.status_code}"
            logging.error(f"Error scraping {url}: {detail}")
            raise RuntimeError(f"Failed to scrape {url}: {detail}")

        data = response.json()
        if not data.get("success"):
            error = data.get("error_message") or "unknown error"
            logging.error(f"Error scraping {url}: {error}")
            raise RuntimeError(f"Failed to scrape {url}: {error}")

        return (data.get("markdown") or "").strip()

    def add_page_snapshot(self, page_snapshot: PageSnapshot) -> None:
        """Adds a new PageSnapshot record to the database"""
        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)

    async def scrape_url(self, url: str, dataset_id: str) -> PageSnapshot:
        logging.info(f"Scraping URL: {url}")

        content = await self._fetch_markdown(url)

        url_hash = PageSnapshot.compute_hash_from_url(url)
        page_snapshot = PageSnapshot(
            url=url,
            user_agent=DEFAULT_USER_AGENT,
            content=content,
            retrieved_at=datetime.now(timezone.utc),
            url_hash=url_hash,
            dataset_id=dataset_id,
        )

        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)

        return page_snapshot

    def save_cleaned_text(
        self, page_snapshot_id: str, content: str, language: str, model: str
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
