"""Tests for generate API endpoints"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.main import app

client = TestClient(app)


@pytest.fixture
def mock_pipeline():
    """Mock DatasetPipeline"""
    with patch("server.api.generate.DatasetPipeline") as mock:
        pipeline_instance = Mock()
        pipeline_instance.process_url = AsyncMock()
        mock.return_value = pipeline_instance
        yield pipeline_instance


@pytest.fixture
def valid_request_data():
    """Valid request data for dataset generation"""
    return {
        "url": "https://example.com",
        "dataset_name": "test_dataset",
        "model_cleaning": "gpt-4-0613",
        "target_language": "fr",
        "model_qa": "gpt-4-0613",
        "similarity_threshold": 0.9,
    }


class TestGenerateDataset:
    """Tests for the generate dataset endpoint"""

    def test_create_dataset_success(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test successful dataset creation"""
        # Mock successful pipeline execution
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-123",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["id"] == "test-id-123"
        assert "dataset_name" in data
        assert data["dataset_name"] == "test_dataset"

    def test_create_dataset_with_defaults(self, mock_pipeline, db: Session):
        """Test dataset creation with minimal parameters (using defaults)"""
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-456",
        }

        minimal_request = {
            "url": "https://example.com",
            "dataset_name": "test_dataset",
        }

        response = client.post("/dataset/generate", json=minimal_request)

        assert response.status_code == 201
        # Verify pipeline was called with default values
        call_args = mock_pipeline.process_url.call_args
        assert call_args is not None

    def test_create_dataset_invalid_cleaning_model(
        self, valid_request_data, db: Session
    ):
        """Test dataset creation with invalid cleaning model"""
        valid_request_data["model_cleaning"] = "invalid-model"

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 400
        assert "not in available models" in response.json()["detail"]

    def test_create_dataset_invalid_qa_model(self, valid_request_data, db: Session):
        """Test dataset creation with invalid QA model"""
        valid_request_data["model_qa"] = "invalid-model"

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 400
        assert "not in available models" in response.json()["detail"]

    def test_create_dataset_invalid_language(self, valid_request_data, db: Session):
        """Test dataset creation with invalid target language"""
        valid_request_data["target_language"] = "invalid-language"

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 400
        assert "Invalid target language" in response.json()["detail"]

    def test_create_dataset_invalid_url(self, db: Session):
        """Test dataset creation with invalid URL format"""
        invalid_request = {
            "url": "not-a-valid-url",
            "dataset_name": "test_dataset",
        }

        response = client.post("/dataset/generate", json=invalid_request)

        # Should fail validation
        assert response.status_code == 422

    def test_create_dataset_missing_required_fields(self, db: Session):
        """Test dataset creation with missing required fields"""
        incomplete_request = {
            "url": "https://example.com",
            # Missing dataset_name
        }

        response = client.post("/dataset/generate", json=incomplete_request)

        assert response.status_code == 422

    def test_create_dataset_with_qa_pairs(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test dataset creation that returns QA pairs"""
        # Mock QA pair objects
        mock_qa = Mock()
        mock_qa.question = "What is this?"
        mock_qa.answer = "This is a test."

        mock_pipeline.process_url.return_value = {
            "qa_pairs": [mock_qa],
            "total": 1,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-789",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        data = response.json()
        assert len(data["qa_pairs"]) == 1
        assert data["qa_pairs"][0]["question"] == "What is this?"
        assert data["total_questions"] == 1

    def test_create_dataset_with_dict_qa_pairs(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test dataset creation with QA pairs as dictionaries"""
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [
                {"question": "Q1?", "answer": "A1"},
                {"question": "Q2?", "answer": "A2"},
            ],
            "total": 2,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-abc",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        data = response.json()
        assert len(data["qa_pairs"]) == 2
        assert data["total_questions"] == 2

    def test_create_dataset_pipeline_exception(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test handling of pipeline exceptions"""
        mock_pipeline.process_url.side_effect = Exception("Pipeline error")

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 500
        assert "error" in response.json()["detail"].lower()

    def test_create_dataset_with_custom_similarity_threshold(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test dataset creation with custom similarity threshold"""
        valid_request_data["similarity_threshold"] = 0.85

        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-def",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        # Verify similarity_threshold was passed to pipeline
        call_kwargs = mock_pipeline.process_url.call_args.kwargs
        assert call_kwargs["similarity_threshold"] == 0.85
        # Check it's in response
        data = response.json()
        assert data["similarity_threshold"] == 0.85

    def test_create_dataset_processing_time_included(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test that processing time is included in response"""
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "dataset_id": "test-id-ghi",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        data = response.json()
        assert "processing_time" in data
        assert isinstance(data["processing_time"], int | float)
        assert data["processing_time"] >= 0

    def test_create_dataset_all_languages(self, mock_pipeline, db: Session):
        """Test dataset creation with all supported languages"""

        def mock_process(*args, **kwargs):
            return {
                "qa_pairs": [],
                "total": 0,
                "exact_duplicates": 0,
                "similar_duplicates": 0,
                "dataset_id": "test-id-multi",
            }

        mock_pipeline.process_url = AsyncMock(side_effect=mock_process)

        languages = ["fr", "en", "es", "de"]
        for i, lang in enumerate(languages):
            request_data = {
                "url": "https://example.com",
                "dataset_name": f"test_{lang}_{i}",
                "target_language": lang,
            }

            response = client.post("/dataset/generate", json=request_data)
            assert response.status_code == 201, f"Failed for language {lang}"

    def test_create_dataset_response_structure(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test that response has correct structure"""
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 5,
            "exact_duplicates": 1,
            "similar_duplicates": 2,
            "dataset_id": "test-id-struct",
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 201
        data = response.json()

        # Check required fields
        assert "id" in data
        assert "dataset_name" in data
        assert "qa_pairs" in data
        assert "processing_time" in data
        assert "model_cleaning" in data
        assert "model_qa" in data
        assert "target_language" in data
        assert "similarity_threshold" in data
        assert "total_questions" in data

    def test_create_dataset_missing_dataset_id(
        self, mock_pipeline, valid_request_data, db: Session
    ):
        """Test handling when dataset_id is missing from pipeline result"""
        mock_pipeline.process_url.return_value = {
            "qa_pairs": [],
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            # dataset_id is missing
        }

        response = client.post("/dataset/generate", json=valid_request_data)

        assert response.status_code == 500
        assert "dataset id" in response.json()["detail"].lower()
