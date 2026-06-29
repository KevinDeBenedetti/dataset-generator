"""Tests for scraper service"""

import httpx
import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from server.services.scraper import ScraperService, DEFAULT_USER_AGENT
from server.models.scraper import PageSnapshot
from server.models.dataset import Dataset


@pytest.fixture
def scraper_service(db: Session):
    """Create a ScraperService instance"""
    return ScraperService(db)


@pytest.fixture
def sample_dataset(db: Session):
    """Create a sample dataset"""
    dataset = Dataset(name="test_dataset", description="Test dataset")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


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

    def test_add_page_snapshot(
        self, scraper_service: ScraperService, db: Session, sample_dataset
    ):
        """Test adding a page snapshot"""
        snapshot = PageSnapshot(
            url="https://example.com",
            user_agent="Test Agent",
            content="Test content",
            retrieved_at=datetime.now(timezone.utc),
            url_hash=PageSnapshot.compute_hash_from_url("https://example.com"),
            dataset_id=sample_dataset.id,
        )

        scraper_service.add_page_snapshot(snapshot)

        # Verify it was added
        saved_snapshot = (
            db.query(PageSnapshot)
            .filter(PageSnapshot.url == "https://example.com")
            .first()
        )
        assert saved_snapshot is not None
        assert saved_snapshot.content == "Test content"

    async def test_scrape_url_success(
        self,
        scraper_service: ScraperService,
        db: Session,
        sample_dataset,
    ):
        """Test successful URL scraping"""
        client_class, _ = _make_httpx_mock(
            markdown="# Main Title\n\nThis is a test paragraph."
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            result = await scraper_service.scrape_url(
                "https://example.com", sample_dataset.id
            )

        assert result.id is not None
        assert result.url == "https://example.com"
        assert "Main Title" in result.content
        assert result.dataset_id == sample_dataset.id
        assert result.user_agent == DEFAULT_USER_AGENT

    async def test_scrape_url_passes_url_to_service(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """Test that the URL is forwarded to the crawl4ai /md endpoint"""
        client_class, post_mock = _make_httpx_mock(markdown="content")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            await scraper_service.scrape_url("https://example.com", sample_dataset.id)

        post_mock.assert_awaited_once()
        assert post_mock.call_args.kwargs["json"]["url"] == "https://example.com"

    async def test_scrape_url_crawl_failure(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """Test that an unsuccessful crawl raises an error"""
        client_class, _ = _make_httpx_mock(success=False, error_message="403 Forbidden")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="403 Forbidden"):
                await scraper_service.scrape_url(
                    "https://example.com/403", sample_dataset.id
                )

    async def test_scrape_url_http_error_status(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """Test that a non-200 response from the service raises an error"""
        client_class, _ = _make_httpx_mock(
            status_code=500, error_message="Internal Server Error"
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="Internal Server Error"):
                await scraper_service.scrape_url(
                    "https://example.com/500", sample_dataset.id
                )

    async def test_scrape_url_request_exception(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """Test that httpx request errors propagate"""
        client_class, _ = _make_httpx_mock(
            post_side_effect=httpx.ConnectError("Connection failed")
        )

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(httpx.HTTPError):
                await scraper_service.scrape_url(
                    "https://unreachable.com", sample_dataset.id
                )

    async def test_scrape_url_creates_hash(
        self,
        scraper_service: ScraperService,
        db: Session,
        sample_dataset,
    ):
        """Test that URL hash is created correctly"""
        client_class, _ = _make_httpx_mock(markdown="Test")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            result = await scraper_service.scrape_url(
                "https://example.com/page", sample_dataset.id
            )

        assert result.url_hash is not None
        assert len(str(result.url_hash)) > 0
        # Verify hash is consistent
        expected_hash = PageSnapshot.compute_hash_from_url("https://example.com/page")
        assert result.url_hash == expected_hash

    def test_save_cleaned_text(
        self, scraper_service: ScraperService, db: Session, sample_dataset
    ):
        """Test saving cleaned text"""
        # First create a page snapshot
        snapshot = PageSnapshot(
            url="https://example.com",
            user_agent="Test Agent",
            content="Original content",
            retrieved_at=datetime.now(timezone.utc),
            url_hash=PageSnapshot.compute_hash_from_url("https://example.com"),
            dataset_id=sample_dataset.id,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        # Save cleaned text
        assert snapshot.id is not None
        assert isinstance(snapshot.id, str)
        cleaned = scraper_service.save_cleaned_text(
            page_snapshot_id=snapshot.id,
            content="Cleaned content here",
            language="french",
            model="gpt-4o-mini",
        )

        assert cleaned.id is not None
        assert cleaned.page_snapshot_id == snapshot.id
        assert cleaned.content == "Cleaned content here"
        assert cleaned.language == "french"
        assert cleaned.model == "gpt-4o-mini"

    async def test_crawl_site_bfs_same_domain(
        self, scraper_service: ScraperService, sample_dataset
    ):
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
            snapshots = await scraper_service.crawl_site(
                "https://example.com", sample_dataset.id, max_depth=1, max_pages=10
            )

        urls = {s.url for s in snapshots}
        assert urls == {
            "https://example.com",
            "https://example.com/a",
            "https://example.com/b",
        }
        # /c is depth 2 (beyond max_depth=1); other.com is a different host.
        assert "https://example.com/c" not in urls
        assert "https://other.com/x" not in urls

    async def test_crawl_site_respects_max_pages(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """Crawl stops once max_pages snapshots are collected."""
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
            snapshots = await scraper_service.crawl_site(
                "https://example.com/0",
                sample_dataset.id,
                max_depth=10,
                max_pages=3,
            )

        assert len(snapshots) == 3

    async def test_crawl_site_per_domain_budget(
        self, scraper_service: ScraperService, sample_dataset
    ):
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
            snapshots = await scraper_service.crawl_site(
                "https://a.com",
                sample_dataset.id,
                max_depth=5,
                max_pages=10,
                same_domain=False,  # allow crossing to b.com
                max_pages_per_domain=1,
            )

        from urllib.parse import urlparse

        hosts = [urlparse(s.url).netloc for s in snapshots]
        # One page per host despite more being reachable.
        assert hosts.count("a.com") == 1
        assert hosts.count("b.com") == 1
        assert len(snapshots) == 2

    async def test_crawl_site_throttles_between_fetches(
        self, scraper_service: ScraperService, sample_dataset
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
                snapshots = await scraper_service.crawl_site(
                    "https://example.com",
                    sample_dataset.id,
                    max_depth=1,
                    max_pages=10,
                    delay_seconds=0.5,
                )

        assert len(snapshots) == 2
        sleep_mock.assert_awaited_once_with(0.5)

    async def test_crawl_site_calls_on_page_per_page(
        self, scraper_service: ScraperService, sample_dataset
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
            snapshots = await scraper_service.crawl_site(
                "https://example.com",
                sample_dataset.id,
                max_depth=1,
                max_pages=10,
                on_page=events.append,
            )

        assert len(events) == len(snapshots) == 2
        assert events[0]["crawled"] == 1
        assert events[1]["crawled"] == 2
        assert all(e["max_pages"] == 10 and "url" in e for e in events)

    async def test_crawl_site_skips_failed_pages(
        self, scraper_service: ScraperService, sample_dataset
    ):
        """A page that fails to fetch is skipped, not fatal to the crawl."""

        async def fake_fetch(url):
            if url == "https://example.com":
                return ("# Home", ["https://example.com/broken"])
            raise RuntimeError("boom")

        with patch.object(scraper_service, "_fetch_page", side_effect=fake_fetch):
            snapshots = await scraper_service.crawl_site(
                "https://example.com", sample_dataset.id, max_depth=2, max_pages=10
            )

        assert [s.url for s in snapshots] == ["https://example.com"]

    async def test_fetch_page_raises_on_unsuccessful_response(
        self, scraper_service: ScraperService
    ):
        """A 200 response with success=false is a soft failure and must raise,
        not be silently ingested as an empty/partial page."""
        client_class, _ = _make_httpx_mock(success=False, error_message="403 Forbidden")

        with patch("server.services.scraper.httpx.AsyncClient", client_class):
            with pytest.raises(RuntimeError, match="403 Forbidden"):
                await scraper_service._fetch_page("https://example.com/403")

    def test_save_cleaned_text_with_empty_content(
        self, scraper_service: ScraperService, db: Session, sample_dataset
    ):
        """Test saving cleaned text with empty content"""
        snapshot = PageSnapshot(
            url="https://example.com",
            user_agent="Test Agent",
            content="Original content",
            retrieved_at=datetime.now(timezone.utc),
            url_hash=PageSnapshot.compute_hash_from_url("https://example.com"),
            dataset_id=sample_dataset.id,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.id is not None
        assert isinstance(snapshot.id, str)
        cleaned = scraper_service.save_cleaned_text(
            page_snapshot_id=snapshot.id,
            content="",
            language="english",
            model="gpt-4o-mini",
        )

        assert cleaned.content == ""
