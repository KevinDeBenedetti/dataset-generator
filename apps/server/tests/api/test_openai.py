"""
Tests for OpenAI API endpoints.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_list_openai_models_success(client: TestClient):
    """Test listing OpenAI models successfully."""
    with patch("server.services.llm.LLMService.get_models") as mock_get_models:
        # Mock the response
        mock_get_models.return_value = [
            "gpt-4",
            "gpt-3.5-turbo",
            "mistral-small-3.1-24b-instruct-2503",
        ]

        response = client.get("/openai/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) == 3
        assert "gpt-4" in data["models"]


def test_list_openai_models_empty(client: TestClient):
    """Test listing OpenAI models when none are available."""
    with patch("server.services.llm.LLMService.get_models") as mock_get_models:
        mock_get_models.return_value = []

        response = client.get("/openai/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert data["models"] == []


def test_list_openai_models_service_failure(client: TestClient):
    """Test listing OpenAI models when service fails."""
    with patch("server.services.llm.LLMService.get_models") as mock_get_models:
        mock_get_models.return_value = None

        response = client.get("/openai/models")
        assert response.status_code == 500
        assert "Unable to retrieve OpenAI models" in response.json()["detail"]


def test_list_openai_models_exception(client: TestClient):
    """Test listing OpenAI models when an exception occurs."""
    with patch("server.services.llm.LLMService.get_models") as mock_get_models:
        mock_get_models.side_effect = Exception("API connection failed")

        with pytest.raises(Exception):
            client.get("/openai/models")
