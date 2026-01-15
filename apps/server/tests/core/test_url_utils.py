"""Tests for URL utilities"""

import pytest

from server.core.utils.url import build_api_url, clean_base_url


class TestCleanBaseUrl:
    """Tests for clean_base_url function"""

    def test_url_without_trailing_slash(self):
        """Test URL without trailing slash gets one added"""
        result = clean_base_url("https://example.com")
        assert result == "https://example.com/"

    def test_url_with_trailing_slash(self):
        """Test URL with trailing slash stays the same"""
        result = clean_base_url("https://example.com/")
        assert result == "https://example.com/"

    def test_url_with_path(self):
        """Test URL with path gets trailing slash"""
        result = clean_base_url("https://example.com/api/v1")
        assert result == "https://example.com/api/v1/"

    def test_empty_url(self):
        """Test empty URL returns empty string"""
        result = clean_base_url("")
        assert result == ""

    def test_invalid_url_no_scheme(self):
        """Test URL without scheme raises ValueError"""
        with pytest.raises(ValueError, match="Invalid URL"):
            clean_base_url("example.com")

    def test_invalid_url_no_netloc(self):
        """Test URL without netloc raises ValueError"""
        with pytest.raises(ValueError, match="Invalid URL"):
            clean_base_url("https://")


class TestBuildApiUrl:
    """Tests for build_api_url function"""

    def test_basic_join(self):
        """Test basic URL joining"""
        result = build_api_url("https://example.com", "api/v1/users")
        assert result == "https://example.com/api/v1/users"

    def test_endpoint_with_leading_slash(self):
        """Test endpoint with leading slash"""
        result = build_api_url("https://example.com/", "/api/v1/users")
        assert result == "https://example.com/api/v1/users"

    def test_base_without_trailing_slash(self):
        """Test base URL without trailing slash"""
        result = build_api_url("https://example.com", "health")
        assert result == "https://example.com/health"

    def test_complex_endpoint(self):
        """Test complex endpoint path"""
        result = build_api_url("https://api.example.com/", "v1/knowledge/123")
        assert result == "https://api.example.com/v1/knowledge/123"
