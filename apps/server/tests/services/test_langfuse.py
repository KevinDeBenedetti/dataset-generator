"""
Tests for Langfuse service functions.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.services.langfuse import (
    create_langfuse_dataset_with_items,
    is_langfuse_available,
    is_langfuse_configured,
    load_json_dataset,
    normalize_dataset_name,
    prepare_langfuse_dataset,
    scan_dataset_files,
)


class TestPrepareLangfuseDataset:
    """Tests for prepare_langfuse_dataset function."""

    def test_basic_dataset_preparation(self):
        """Test basic dataset preparation with valid data."""
        data = [
            {
                "id": "q1",
                "question": "What is Python?",
                "answer": "A programming language",
                "confidence": 0.95,
                "context": "Python programming",
            }
        ]

        dataset, items = prepare_langfuse_dataset(data, "test-dataset")

        assert dataset["name"] == "test-dataset"
        assert "description" in dataset
        assert dataset["metadata"]["total_items"] == 1
        assert len(items) == 1
        assert items[0]["id"] == "q1"
        assert items[0]["input"]["question"] == "What is Python?"
        assert items[0]["expected_output"]["answer"] == "A programming language"

    def test_dataset_with_missing_optional_fields(self):
        """Test dataset preparation when optional fields are missing."""
        data = [{"question": "Test?", "answer": "Answer"}]

        _dataset, items = prepare_langfuse_dataset(data, "minimal-dataset")

        assert len(items) == 1
        assert items[0]["id"] == "item_0"
        assert items[0]["metadata"]["confidence"] == 1.0
        assert items[0]["metadata"]["context"] == ""

    def test_multiple_items(self):
        """Test dataset preparation with multiple items."""
        data = [
            {"id": f"q{i}", "question": f"Question {i}?", "answer": f"Answer {i}"}
            for i in range(5)
        ]

        dataset, items = prepare_langfuse_dataset(data, "multi-dataset")

        assert dataset["metadata"]["total_items"] == 5
        assert len(items) == 5


class TestLoadJsonDataset:
    """Tests for load_json_dataset function."""

    def test_load_valid_json(self):
        """Test loading a valid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"question": "Test?", "answer": "Answer"}], f)
            temp_path = Path(f.name)

        try:
            data = load_json_dataset(temp_path)
            assert len(data) == 1
            assert data[0]["question"] == "Test?"
        finally:
            temp_path.unlink()

    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_json_dataset(Path("/nonexistent/file.json"))

    def test_load_invalid_json(self):
        """Test loading an invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid JSON file"):
                load_json_dataset(temp_path)
        finally:
            temp_path.unlink()

    def test_load_directory_instead_of_file(self):
        """Test loading a directory instead of a file."""
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            pytest.raises(FileNotFoundError),
        ):
            load_json_dataset(Path(temp_dir))


class TestScanDatasetFiles:
    """Tests for scan_dataset_files function."""

    def test_scan_directory_with_json_files(self):
        """Test scanning a directory with JSON files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "file1.json").touch()
            (temp_path / "file2.json").touch()
            (temp_path / "not_json.txt").touch()

            files = scan_dataset_files(temp_path)

            assert len(files) == 2
            assert "file1.json" in files
            assert "file2.json" in files
            assert "not_json.txt" not in files

    def test_scan_empty_directory(self):
        """Test scanning an empty directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            files = scan_dataset_files(Path(temp_dir))
            assert files == []

    def test_scan_nonexistent_directory(self):
        """Test scanning a directory that doesn't exist."""
        files = scan_dataset_files(Path("/nonexistent/directory"))
        assert files == []


class TestCreateLangfuseDatasetWithItems:
    """Tests for create_langfuse_dataset_with_items function."""

    def test_create_dataset_success(self):
        """Test successful dataset creation."""
        mock_client = MagicMock()
        mock_dataset = MagicMock()
        mock_dataset.id = "dataset-123"
        mock_client.create_dataset.return_value = mock_dataset

        mock_item = MagicMock()
        mock_item.id = "item-1"
        mock_client.create_dataset_item.return_value = mock_item

        config = {"name": "test-dataset", "description": "Test"}
        items = [
            {
                "id": "item-1",
                "input": {"question": "Test?"},
                "expected_output": {"answer": "Answer"},
                "metadata": {},
            }
        ]

        result = create_langfuse_dataset_with_items(config, items, mock_client)

        assert result["dataset_id"] == "dataset-123"
        assert result["created_count"] == 1
        assert result["failed_count"] == 0

    def test_create_dataset_with_failed_items(self):
        """Test dataset creation with some failed items."""
        mock_client = MagicMock()
        mock_dataset = MagicMock()
        mock_dataset.id = "dataset-123"
        mock_client.create_dataset.return_value = mock_dataset
        mock_client.create_dataset_item.side_effect = Exception("Item creation failed")

        config = {"name": "test-dataset"}
        items = [
            {
                "id": "item-1",
                "input": {"question": "Test?"},
                "expected_output": {"answer": "Answer"},
                "metadata": {},
            }
        ]

        result = create_langfuse_dataset_with_items(config, items, mock_client)

        assert result["created_count"] == 0
        assert result["failed_count"] == 1

    def test_create_dataset_uses_default_client(self):
        """Test that default client is used when none provided."""
        with patch("server.services.langfuse.get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_dataset = MagicMock()
            mock_dataset.id = "dataset-123"
            mock_client.create_dataset.return_value = mock_dataset
            mock_get_client.return_value = mock_client

            config = {"name": "test-dataset"}
            items = []

            create_langfuse_dataset_with_items(config, items)

            mock_get_client.assert_called_once()


class TestNormalizeDatasetName:
    """Tests for normalize_dataset_name function."""

    def test_basic_normalization(self):
        """Test basic filename normalization."""
        assert normalize_dataset_name("my_dataset.json") == "my-dataset"
        assert normalize_dataset_name("test dataset.json") == "test-dataset"

    def test_path_with_directories(self):
        """Test normalization with full path."""
        assert normalize_dataset_name("/path/to/my_file.json") == "my-file"

    def test_no_extension(self):
        """Test normalization without extension."""
        assert normalize_dataset_name("dataset_name") == "dataset-name"


class TestIsLangfuseConfigured:
    """Tests for is_langfuse_configured function."""

    def test_all_vars_present(self):
        """Test when all required env vars are present."""
        with patch.dict(
            "os.environ",
            {
                "LANGFUSE_SECRET_KEY": "secret",
                "LANGFUSE_PUBLIC_KEY": "public",
                "LANGFUSE_HOST": "https://langfuse.example.com",
            },
        ):
            assert is_langfuse_configured() is True

    def test_missing_vars(self):
        """Test when required env vars are missing."""
        with patch.dict("os.environ", {}, clear=True):
            assert is_langfuse_configured() is False

    def test_partial_vars(self):
        """Test when some required env vars are missing."""
        with patch.dict("os.environ", {"LANGFUSE_SECRET_KEY": "secret"}, clear=True):
            assert is_langfuse_configured() is False


class TestIsLangfuseAvailable:
    """Tests for is_langfuse_available function."""

    def test_available_when_configured_and_client_works(self):
        """Test availability when configured and client initializes."""
        with (
            patch("server.services.langfuse.is_langfuse_configured", return_value=True),
            patch("server.services.langfuse.get_client") as mock_get,
        ):
            mock_get.return_value = MagicMock()
            assert is_langfuse_available() is True

    def test_not_available_when_not_configured(self):
        """Test not available when not configured."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=False
        ):
            assert is_langfuse_available() is False

    def test_not_available_when_client_fails(self):
        """Test not available when client initialization fails."""
        with (
            patch("server.services.langfuse.is_langfuse_configured", return_value=True),
            patch("server.services.langfuse.get_client") as mock_get,
        ):
            mock_get.side_effect = Exception("Connection failed")
            assert is_langfuse_available() is False
