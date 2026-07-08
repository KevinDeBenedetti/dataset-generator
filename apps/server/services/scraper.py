import asyncio
import logging
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from server.core.config import config


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class ScrapedPage:
    """A page fetched by the scraper, held in memory only.

    The scraper is stateless: it fetches page content and hands it back for the
    pipeline to clean and mine for QA pairs — nothing is written to the
    database. Carries just the URL and its Markdown content.
    """

    url: str
    content: str


class ScraperService:
    """Stateless page fetcher.

    Retrieves Markdown from the crawl4ai service and walks a site
    breadth-first. It holds no database session and persists nothing; callers
    receive :class:`ScrapedPage` values to process in memory.
    """

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

    async def scrape_url(self, url: str) -> ScrapedPage:
        logging.info(f"Scraping URL: {url}")
        content = await self._fetch_markdown(url)
        return ScrapedPage(url=url, content=content)

    async def crawl_site(
        self,
        seed_url: str,
        max_depth: int | None = None,
        max_pages: int | None = None,
        same_domain: bool | None = None,
        delay_seconds: float | None = None,
        max_pages_per_domain: int | None = None,
        on_page: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[ScrapedPage]:
        """Breadth-first crawl from ``seed_url``, returning one page per URL.

        Follows internal links up to ``max_depth`` hops and ``max_pages`` pages.
        With ``same_domain`` (default), only links on the seed's host are
        followed. Pages that fail to fetch are skipped (logged) rather than
        aborting the whole crawl, so one broken link can't sink the dataset.

        Cost controls: ``delay_seconds`` throttles the crawler by pausing between
        page fetches (0 = no throttle), and ``max_pages_per_domain`` caps how many
        pages are taken from any single host (0 = unlimited). Both default to the
        ``CRAWL_*`` config values.

        ``on_page`` (optional) is called after each page is successfully fetched
        with a small progress dict, so callers can stream live crawl progress.
        """
        max_depth = config.crawl_max_depth if max_depth is None else max_depth
        max_pages = config.crawl_max_pages if max_pages is None else max_pages
        same_domain = config.crawl_same_domain if same_domain is None else same_domain
        delay_seconds = (
            config.crawl_delay_seconds if delay_seconds is None else delay_seconds
        )
        max_pages_per_domain = (
            config.crawl_max_pages_per_domain
            if max_pages_per_domain is None
            else max_pages_per_domain
        )

        seed = urldefrag(seed_url)[0]
        seed_host = urlparse(seed).netloc

        visited: set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(seed, 0)])
        pages: List[ScrapedPage] = []
        # Pages kept per host, to enforce the optional per-domain budget.
        per_domain: Counter[str] = Counter()
        fetches = 0

        while queue and len(pages) < max_pages:
            current, depth = queue.popleft()
            current = urldefrag(current)[0]
            if current in visited:
                continue
            visited.add(current)

            # Per-domain budget: skip fetching once a host hits its cap, so the
            # crawl can't spend its whole page budget on a single domain.
            domain = urlparse(current).netloc
            if max_pages_per_domain and per_domain[domain] >= max_pages_per_domain:
                logging.info(
                    f"Skipping {current}: per-domain budget reached for {domain} "
                    f"({max_pages_per_domain})"
                )
                continue

            # Throttle between network fetches (not before the first one).
            if delay_seconds and fetches:
                await asyncio.sleep(delay_seconds)
            fetches += 1

            try:
                content, hrefs = await self._fetch_page(current)
            except Exception as exc:  # noqa: BLE001 — one bad page must not abort
                logging.warning(f"Skipping {current}: {exc}")
                continue

            if content:
                pages.append(ScrapedPage(url=current, content=content))
                per_domain[domain] += 1
                logging.info(
                    f"Crawled {current} (depth {depth}) — "
                    f"{len(pages)}/{max_pages} pages"
                )
                if on_page is not None:
                    on_page(
                        {
                            "url": current,
                            "depth": depth,
                            "crawled": len(pages),
                            "max_pages": max_pages,
                        }
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

        logging.info(f"Crawl finished: {len(pages)} pages from {seed}")
        return pages
