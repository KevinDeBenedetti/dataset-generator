"""Tests for scraper service"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import requests

from server.services.scraper import ScraperService
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


@pytest.fixture
def sample_html():
    """Sample HTML content for testing"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <script>console.log('test');</script>
        <style>body { color: black; }</style>
    </head>
    <body>
        <!-- This is a comment -->
        <h1>Main Title</h1>
        <p>This is a test paragraph.</p>
        <p>Another paragraph with content.</p>
    </body>
    </html>
    """


class TestScraperService:
    """Tests for ScraperService class"""

    def test_setup_session(self, scraper_service: ScraperService):
        """Test session setup with retries"""
        session = scraper_service._setup_session()

        assert isinstance(session, requests.Session)
        # Verify adapters are mounted
        assert "https://" in session.adapters
        assert "http://" in session.adapters

    def test_get_user_agent(self, scraper_service: ScraperService):
        """Test getting a user agent"""
        user_agent = scraper_service._get_user_agent()

        assert isinstance(user_agent, str)
        assert len(user_agent) > 0
        # Should contain common user agent strings
        assert any(
            keyword in user_agent.lower()
            for keyword in ["mozilla", "chrome", "safari", "firefox", "windows", "mac"]
        )

    @patch("server.services.scraper.UserAgent")
    def test_get_user_agent_fallback(
        self, mock_ua_class, scraper_service: ScraperService
    ):
        """Test user agent fallback when fake-useragent fails"""
        mock_ua_class.side_effect = Exception("fake-useragent error")

        user_agent = scraper_service._get_user_agent()

        assert (
            user_agent == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    def test_extract_text_basic(self, scraper_service: ScraperService, sample_html):
        """Test basic text extraction from HTML"""
        text = scraper_service._extract_text(sample_html)

        assert "Main Title" in text
        assert "This is a test paragraph." in text
        assert "Another paragraph with content." in text
        # Scripts and styles should be removed
        assert "console.log" not in text
        assert "color: black" not in text
        # Comments should be removed
        assert "This is a comment" not in text

    def test_extract_text_removes_scripts(self, scraper_service: ScraperService):
        """Test that script tags are removed"""
        html = """
        <html><body>
            <p>Visible text</p>
            <script>alert('hidden');</script>
            <p>More visible text</p>
        </body></html>
        """
        text = scraper_service._extract_text(html)

        assert "Visible text" in text
        assert "More visible text" in text
        assert "alert" not in text
        assert "hidden" not in text

    def test_extract_text_removes_styles(self, scraper_service: ScraperService):
        """Test that style tags are removed"""
        html = """
        <html><body>
            <p>Visible text</p>
            <style>p { color: red; }</style>
            <p>More visible text</p>
        </body></html>
        """
        text = scraper_service._extract_text(html)

        assert "Visible text" in text
        assert "color: red" not in text

    def test_extract_text_normalizes_whitespace(self, scraper_service: ScraperService):
        """Test whitespace normalization"""
        html = """
        <html><body>
            <p>Text   with    multiple     spaces</p>
            <p>Text
            with
            newlines</p>
        </body></html>
        """
        text = scraper_service._extract_text(html)

        # Multiple spaces should be normalized to single space
        assert "multiple     spaces" not in text
        assert "multiple spaces" in text or "Text with" in text

    def test_extract_text_empty_html(self, scraper_service: ScraperService):
        """Test extraction from empty HTML"""
        html = "<html><body></body></html>"
        text = scraper_service._extract_text(html)

        assert text == ""

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

    @patch("server.services.scraper.requests.Session.get")
    @patch("server.services.scraper.time.sleep")
    def test_scrape_url_success(
        self,
        mock_sleep,
        mock_get,
        scraper_service: ScraperService,
        db: Session,
        sample_dataset,
        sample_html,
    ):
        """Test successful URL scraping"""
        # Mock response
        mock_response = Mock()
        mock_response.text = sample_html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = scraper_service.scrape_url("https://example.com", sample_dataset.id)

        assert result.id is not None
        assert result.url == "https://example.com"
        assert "Main Title" in result.content
        assert result.dataset_id == sample_dataset.id
        # Verify sleep was called (rate limiting)
        mock_sleep.assert_called_once()

    @patch("server.services.scraper.requests.Session.get")
    def test_scrape_url_http_error(
        self, mock_get, scraper_service: ScraperService, sample_dataset
    ):
        """Test scraping with HTTP error"""
        mock_get.side_effect = requests.HTTPError("404 Not Found")

        with pytest.raises(requests.HTTPError):
            scraper_service.scrape_url("https://example.com/404", sample_dataset.id)

    @patch("server.services.scraper.requests.Session.get")
    def test_scrape_url_timeout(
        self, mock_get, scraper_service: ScraperService, sample_dataset
    ):
        """Test scraping with timeout"""
        mock_get.side_effect = requests.Timeout("Request timeout")

        with pytest.raises(requests.Timeout):
            scraper_service.scrape_url("https://slow-example.com", sample_dataset.id)

    @patch("server.services.scraper.requests.Session.get")
    def test_scrape_url_connection_error(
        self, mock_get, scraper_service: ScraperService, sample_dataset
    ):
        """Test scraping with connection error"""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        with pytest.raises(requests.ConnectionError):
            scraper_service.scrape_url("https://unreachable.com", sample_dataset.id)

    @patch("server.services.scraper.requests.Session.get")
    @patch("server.services.scraper.time.sleep")
    def test_scrape_url_creates_hash(
        self,
        mock_sleep,
        mock_get,
        scraper_service: ScraperService,
        db: Session,
        sample_dataset,
    ):
        """Test that URL hash is created correctly"""
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = scraper_service.scrape_url(
            "https://example.com/page", sample_dataset.id
        )

        assert result.url_hash is not None
        assert len(result.url_hash) > 0
        # Verify hash is consistent
        expected_hash = PageSnapshot.compute_hash_from_url("https://example.com/page")
        assert result.url_hash == expected_hash

    @patch("server.services.scraper.requests.Session.get")
    @patch("server.services.scraper.time.sleep")
    def test_scrape_url_sets_user_agent(
        self, mock_sleep, mock_get, scraper_service: ScraperService, sample_dataset
    ):
        """Test that user agent is set in request"""
        mock_response = Mock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        scraper_service.scrape_url("https://example.com", sample_dataset.id)

        # Verify get was called with headers containing User-Agent
        call_args = mock_get.call_args
        assert call_args is not None
        headers = call_args.kwargs.get("headers", {})
        assert "User-Agent" in headers

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
        cleaned = scraper_service.save_cleaned_text(
            page_snapshot_id=int(snapshot.id),
            content="Cleaned content here",
            language="french",
            model="gpt-4o-mini",
        )

        assert cleaned.id is not None
        assert cleaned.page_snapshot_id == snapshot.id
        assert cleaned.content == "Cleaned content here"
        assert cleaned.language == "french"
        assert cleaned.model == "gpt-4o-mini"

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

        cleaned = scraper_service.save_cleaned_text(
            page_snapshot_id=int(snapshot.id),
            content="",
            language="english",
            model="gpt-4o-mini",
        )

        assert cleaned.content == ""

    @patch("server.services.scraper.requests.Session.get")
    @patch("server.services.scraper.time.sleep")
    def test_scrape_url_with_complex_html(
        self,
        mock_sleep,
        mock_get,
        scraper_service: ScraperService,
        db: Session,
        sample_dataset,
    ):
        """Test scraping URL with complex HTML structure"""
        complex_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Complex Page</title>
        </head>
        <body>
            <nav>Navigation</nav>
            <main>
                <article>
                    <h1>Article Title</h1>
                    <p>Article content</p>
                </article>
            </main>
            <footer>Footer content</footer>
        </body>
        </html>
        """
        mock_response = Mock()
        mock_response.text = complex_html
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        result = scraper_service.scrape_url("https://example.com", sample_dataset.id)

        assert "Article Title" in result.content
        assert "Article content" in result.content
