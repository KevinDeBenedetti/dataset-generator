"""Tests for the (stateless) scraper service.

The scraper fetches page content and returns :class:`ScrapedPage` values in
memory — it holds no database session and persists nothing.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, Mock, patch

from server.services.scraper import ScraperService, ScrapedPage


@pytest.fixture
def scraper_service():
    """Create a ScraperService instance (stateless — no DB)."""
    return ScraperService()


def _make_httpx_mock(
    markdown="",
    success=True,
    status_code=200,
    error_message=None,
    post_side_effect=None,
):
    """Build a mock for httpx.AsyncClient used as an async context manager.

    Returns (client_class_mock, post_mock).
    """
    response = Mock()
    response.status_code = status_code
    response.text = error_message or ""
    response.json = Mock(
        return_value={
            "markdown": markdown,
            "success": success,
            "error_message": error_message,
        }
    )

    client = Mock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    else:
        client.post = AsyncMock(return_value=response)

    context_manager = Mock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    client_class = Mock(return_value=context_manager)
    return client_class, client.post


class TestScraperService:
    """Tests for ScraperService class"""

    async def test_scrape_url_success(self, scraper_service: ScraperService):
        """Successful scraping returns an in-memory ScrapedPage."""
        client_class, _ = _make_httpx_mock(
            markdown="# Main Title\n\nThis is a test paragraph."
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            result = await scraper_service.scrape_url("https://example.com")

        assert isinstance(result, ScrapedPage)
        assert result.url == "https://example.com"
        assert "Main Title" in result.content

    async def test_scrape_url_passes_url_to_service(
        self, scraper_service: ScraperService
    ):
        """Test that the URL is forwarded to the crawl4ai /md endpoint"""
        client_class, post_mock = _make_httpx_mock(markdown="content")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            await scraper_service.scrape_url("https://example.com")

        post_mock.assert_awaited_once()
        assert post_mock.call_args.kwargs["json"]["url"] == "https://example.com"

    async def test_scrape_url_crawl_failure(self, scraper_service: ScraperService):
        """Test that an unsuccessful crawl raises an error"""
        client_class, _ = _make_httpx_mock(success=False, error_message="403 Forbidden")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="403 Forbidden"):
                await scraper_service.scrape_url("https://example.com/403")

    async def test_scrape_url_http_error_status(self, scraper_service: ScraperService):
        """Test that a non-200 response from the service raises an error"""
        client_class, _ = _make_httpx_mock(
            status_code=500, error_message="Internal Server Error"
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="Internal Server Error"):
                await scraper_service.scrape_url("https://example.com/500")

    async def test_scrape_url_request_exception(self, scraper_service: ScraperService):
        """Test that httpx request errors propagate"""
        client_class, _ = _make_httpx_mock(
            post_side_effect=httpx.ConnectError("Connection failed")
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(httpx.HTTPError):
                await scraper_service.scrape_url("https://unreachable.com")

    async def test_crawl_site_bfs_same_domain(self, scraper_service: ScraperService):
        """Crawl follows same-domain links breadth-first within max_depth."""
        pages = {
            "https://example.com": (
                "# Home",
                [
                    "https://example.com/a",
                    "https://other.com/x",  # external — must be skipped
                    "https://example.com/b",
                ],
            ),
            "https://example.com/a": ("# A", ["https://example.com/c"]),
            "https://example.com/b": ("# B", []),
            "https://example.com/c": ("# C", []),
        }

        async def fake_fetch(url):
            return pages.get(url, ("", []))

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            result = await scraper_service.crawl_site(
                "https://example.com", max_depth=1, max_pages=10
            )

        urls = {p.url for p in result}
        assert urls == {
            "https://example.com",
            "https://example.com/a",
            "https://example.com/b",
        }
        # /c is depth 2 (beyond max_depth=1); other.com is a different host.
        assert "https://example.com/c" not in urls
        assert "https://other.com/x" not in urls

    async def test_crawl_site_respects_max_pages(self, scraper_service: ScraperService):
        """Crawl stops once max_pages pages are collected."""
        pages = {
            f"https://example.com/{i}": (
                f"# Page {i}",
                [f"https://example.com/{i + 1}"],
            )
            for i in range(10)
        }

        async def fake_fetch(url):
            return pages.get(url, ("", []))

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            result = await scraper_service.crawl_site(
                "https://example.com/0",
                max_depth=10,
                max_pages=3,
            )

        assert len(result) == 3

    async def test_crawl_site_per_domain_budget(self, scraper_service: ScraperService):
        """max_pages_per_domain caps how many pages are taken from each host."""
        pages = {
            "https://a.com": ("# A0", ["https://a.com/1", "https://b.com"]),
            "https://a.com/1": ("# A1", []),
            "https://b.com": ("# B0", ["https://b.com/1"]),
            "https://b.com/1": ("# B1", []),
        }

        async def fake_fetch(url):
            return pages.get(url, ("", []))

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            result = await scraper_service.crawl_site(
                "https://a.com",
                max_depth=5,
                max_pages=10,
                same_domain=False,  # allow crossing to b.com
                max_pages_per_domain=1,
            )

        from urllib.parse import urlparse

        hosts = [urlparse(p.url).netloc for p in result]
        # One page per host despite more being reachable.
        assert hosts.count("a.com") == 1
        assert hosts.count("b.com") == 1
        assert len(result) == 2

    async def test_crawl_site_throttles_between_fetches(
        self, scraper_service: ScraperService
    ):
        """delay_seconds pauses between fetches (once for two pages, not before
        the first)."""
        pages = {
            "https://example.com": ("# Home", ["https://example.com/a"]),
            "https://example.com/a": ("# A", []),
        }

        async def fake_fetch(url):
            return pages.get(url, ("", []))

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            with patch(
                "server.services.scraper.asyncio.sleep", new=AsyncMock()
            ) as sleep_mock:
                result = await scraper_service.crawl_site(
                    "https://example.com",
                    max_depth=1,
                    max_pages=10,
                    delay_seconds=0.5,
                )

        assert len(result) == 2
        sleep_mock.assert_awaited_once_with(0.5)

    async def test_crawl_site_calls_on_page_per_page(
        self, scraper_service: ScraperService
    ):
        """on_page is invoked once per crawled page with progress info."""
        pages = {
            "https://example.com": ("# Home", ["https://example.com/a"]),
            "https://example.com/a": ("# A", []),
        }

        async def fake_fetch(url):
            return pages.get(url, ("", []))

        events: list[dict] = []

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            result = await scraper_service.crawl_site(
                "https://example.com",
                max_depth=1,
                max_pages=10,
                on_page=events.append,
            )

        assert len(events) == len(result) == 2
        assert events[0]["crawled"] == 1
        assert events[1]["crawled"] == 2
        assert all(e["max_pages"] == 10 and "url" in e for e in events)

    async def test_crawl_site_skips_failed_pages(self, scraper_service: ScraperService):
        """A page that fails to fetch is skipped, not fatal to the crawl."""

        async def fake_fetch(url):
            if url == "https://example.com":
                return ("# Home", ["https://example.com/broken"])
            raise RuntimeError("boom")

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            result = await scraper_service.crawl_site(
                "https://example.com", max_depth=2, max_pages=10
            )

        assert [p.url for p in result] == ["https://example.com"]

    async def test_fetch_page_raises_on_unsuccessful_response(
        self, scraper_service: ScraperService
    ):
        """A 200 response with success=false is a soft failure and must raise,
        not be silently ingested as an empty/partial page."""
        client_class, _ = _make_httpx_mock(success=False, error_message="403 Forbidden")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="403 Forbidden"):
                await scraper_service._fetch_page("https://example.com/403")
