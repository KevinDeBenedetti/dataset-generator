import logging
from collections import deque
from datetime import datetime, timezone
from typing import List, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

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

    async def _fetch_page(self, url: str) -> Tuple[str, List[str]]:
        """Fetch a page via crawl4ai's ``/crawl`` endpoint.

        Unlike ``/md``, this returns the full crawl result, so we get both the
        Markdown and the list of internal links — what we need to walk the site
        breadth-first. Returns ``(markdown, internal_hrefs)``; an empty markdown
        means the page could not be rendered.
        """
        endpoint = f"{config.crawl4ai_base_url.rstrip('/')}/crawl"
        headers = {}
        if config.crawl4ai_api_token:
            headers["Authorization"] = f"Bearer {config.crawl4ai_api_token}"

        async with httpx.AsyncClient(timeout=config.crawl4ai_timeout) as client:
            response = await client.post(
                endpoint, json={"urls": [url]}, headers=headers
            )

        if response.status_code != 200:
            detail = response.text or f"HTTP {response.status_code}"
            raise RuntimeError(f"Failed to crawl {url}: {detail}")

        data = response.json()
        # crawl4ai can return HTTP 200 with success=false for a soft failure
        # (blocked page, render error). Reject it like _fetch_markdown does,
        # rather than silently ingesting partial/garbage markdown.
        if not data.get("success", True):
            error = data.get("error_message") or "unknown error"
            logging.error(f"Error crawling {url}: {error}")
            raise RuntimeError(f"Failed to crawl {url}: {error}")

        results = data.get("results") or data.get("result") or []
        if isinstance(results, dict):
            results = [results]
        if not results:
            return "", []

        result = results[0]

        # Markdown can be a plain string or a {"raw_markdown": ...} object.
        markdown = result.get("markdown") or ""
        if isinstance(markdown, dict):
            markdown = markdown.get("raw_markdown") or markdown.get("markdown") or ""

        links = result.get("links") or {}
        internal = links.get("internal") or []
        hrefs: List[str] = []
        for link in internal:
            href = link.get("href") if isinstance(link, dict) else link
            if href:
                hrefs.append(href)

        return markdown.strip(), hrefs

    def add_page_snapshot(self, page_snapshot: PageSnapshot) -> None:
        """Adds a new PageSnapshot record to the database"""
        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)

    def _save_snapshot(self, url: str, content: str, dataset_id: str) -> PageSnapshot:
        """Persist a fetched page as a PageSnapshot."""
        page_snapshot = PageSnapshot(
            url=url,
            user_agent=DEFAULT_USER_AGENT,
            content=content,
            retrieved_at=datetime.now(timezone.utc),
            url_hash=PageSnapshot.compute_hash_from_url(url),
            dataset_id=dataset_id,
        )
        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)
        return page_snapshot

    async def scrape_url(self, url: str, dataset_id: str) -> PageSnapshot:
        logging.info(f"Scraping URL: {url}")
        content = await self._fetch_markdown(url)
        return self._save_snapshot(url, content, dataset_id)

    async def crawl_site(
        self,
        seed_url: str,
        dataset_id: str,
        max_depth: int | None = None,
        max_pages: int | None = None,
        same_domain: bool | None = None,
    ) -> List[PageSnapshot]:
        """Breadth-first crawl from ``seed_url``, saving one snapshot per page.

        Follows internal links up to ``max_depth`` hops and ``max_pages`` pages.
        With ``same_domain`` (default), only links on the seed's host are
        followed. Pages that fail to fetch are skipped (logged) rather than
        aborting the whole crawl, so one broken link can't sink the dataset.
        """
        max_depth = config.crawl_max_depth if max_depth is None else max_depth
        max_pages = config.crawl_max_pages if max_pages is None else max_pages
        same_domain = config.crawl_same_domain if same_domain is None else same_domain

        seed = urldefrag(seed_url)[0]
        seed_host = urlparse(seed).netloc

        visited: set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(seed, 0)])
        snapshots: List[PageSnapshot] = []

        while queue and len(snapshots) < max_pages:
            current, depth = queue.popleft()
            current = urldefrag(current)[0]
            if current in visited:
                continue
            visited.add(current)

            try:
                content, hrefs = await self._fetch_page(current)
            except Exception as exc:  # noqa: BLE001 — one bad page must not abort
                logging.warning(f"Skipping {current}: {exc}")
                continue

            if content:
                snapshots.append(self._save_snapshot(current, content, dataset_id))
                logging.info(
                    f"Crawled {current} (depth {depth}) — "
                    f"{len(snapshots)}/{max_pages} pages"
                )

            if depth >= max_depth:
                continue

            for href in hrefs:
                target = urldefrag(urljoin(current, href))[0]
                if target in visited:
                    continue
                if same_domain and urlparse(target).netloc != seed_host:
                    continue
                if not urlparse(target).scheme.startswith("http"):
                    continue
                queue.append((target, depth + 1))

        logging.info(f"Crawl finished: {len(snapshots)} pages from {seed}")
        return snapshots

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
