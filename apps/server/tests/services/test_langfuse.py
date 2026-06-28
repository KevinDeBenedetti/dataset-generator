"""
Tests for Langfuse service functions.
"""

import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from server.services.langfuse import (
    prepare_langfuse_dataset,
    load_json_dataset,
    scan_dataset_files,
    create_langfuse_dataset_with_items,
    normalize_dataset_name,
    is_langfuse_configured,
    is_langfuse_available,
    get_next_dataset_version,
    sync_qa_to_langfuse,
    list_dataset_runs,
    list_datasets,
    get_dataset_items,
    delete_dataset_item,
    reset_langfuse_availability_cache,
)


class TestDatasetVersioning:
    """Tests for the DVC-like Langfuse versioning helpers."""

    def test_next_version_counts_existing_runs(self):
        """The next version is the run count + 1."""
        client = MagicMock()
        runs = MagicMock()
        runs.data = [MagicMock(), MagicMock()]
        client.get_dataset_runs.return_value = runs

        assert get_next_dataset_version("ds", client) == 3
        client.get_dataset_runs.assert_called_once_with(dataset_name="ds")

    def test_next_version_defaults_to_one(self):
        """A brand-new dataset (no runs / error) starts at version 1."""
        client = MagicMock()
        client.get_dataset_runs.side_effect = Exception("not found")

        assert get_next_dataset_version("ds", client) == 1

    def test_sync_creates_dataset_items_and_run(self):
        """Sync upserts the dataset, each item, and records a versioned run."""
        client = MagicMock()
        client.get_dataset_runs.return_value = MagicMock(data=[])
        client.start_observation.return_value = MagicMock(trace_id="trace-xyz")

        items = [
            {
                "id": "hash1",
                "input": {"question": "q1"},
                "expected_output": {"answer": "a1"},
                "metadata": {"context_length": 10},
            },
            {
                "id": "hash2",
                "input": {"question": "q2"},
                "expected_output": {"answer": "a2"},
                "metadata": {},
            },
        ]

        result = sync_qa_to_langfuse(
            "my-dataset",
            items,
            source_url="https://example.com",
            stats={"total": 2},
            langfuse_client=client,
        )

        # Dataset created with version metadata.
        create_kwargs = client.create_dataset.call_args.kwargs
        assert create_kwargs["name"] == "my-dataset"
        assert create_kwargs["metadata"]["version"] == 1
        assert create_kwargs["metadata"]["source_url"] == "https://example.com"

        # Both items synced, each stamped with the version.
        assert client.create_dataset_item.call_count == 2
        item_kwargs = client.create_dataset_item.call_args_list[0].kwargs
        assert item_kwargs["id"] == "hash1"
        assert item_kwargs["metadata"]["version"] == 1

        # A versioned dataset run was recorded by linking each item to the run
        # directly (no run_experiment / get_dataset / per-item task execution).
        client.get_dataset.assert_not_called()
        link = client.api.dataset_run_items.create
        assert link.call_count == 2
        link_kwargs = link.call_args_list[0].kwargs
        assert link_kwargs["run_name"] == "v1"
        assert link_kwargs["dataset_item_id"] == "hash1"
        assert link_kwargs["metadata"]["version"] == 1
        # Each item is linked to the single run trace (the API requires a trace).
        assert link_kwargs["trace_id"] == "trace-xyz"
        client.start_observation.assert_called_once()
        client.flush.assert_called_once()

        assert result["version"] == 1
        assert result["run_name"] == "v1"
        assert result["created_count"] == 2
        assert result["failed_count"] == 0

    def test_list_dataset_runs_newest_first(self):
        """Runs are summarised and returned newest (highest version) first."""
        client = MagicMock()
        run1 = MagicMock(
            name="v1",
            description="gen v1",
            metadata={"version": 1, "item_count": 5, "source_url": "https://a"},
            created_at=None,
        )
        run1.name = "v1"
        run2 = MagicMock()
        run2.name = "v2"
        run2.description = "gen v2"
        run2.metadata = {"version": 2, "item_count": 8, "source_url": "https://a"}
        run2.created_at = None
        client.get_dataset_runs.return_value = MagicMock(data=[run1, run2])

        versions = list_dataset_runs("ds", client)

        client.get_dataset_runs.assert_called_once_with(dataset_name="ds")
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["run_name"] == "v2"
        assert versions[0]["item_count"] == 8

    def test_list_dataset_runs_empty(self):
        """No runs → empty list (not an error)."""
        client = MagicMock()
        client.get_dataset_runs.return_value = MagicMock(data=[])
        assert list_dataset_runs("ds", client) == []


class TestListDatasets:
    def _dataset(self, name, created_at, *, total_items=None, version=None):
        d = MagicMock()
        d.id = name
        d.name = name
        d.description = f"desc {name}"
        d.metadata = {"total_items": total_items, "version": version}
        d.created_at = created_at
        d.updated_at = created_at
        return d

    def test_summarizes_and_sorts_newest_first(self):
        client = MagicMock()
        d_old = self._dataset("alpha", "2026-01-01T00:00:00", total_items=5, version=1)
        d_new = self._dataset("beta", "2026-02-01T00:00:00", total_items=8, version=2)
        page = MagicMock(data=[d_old, d_new], meta=MagicMock(total_pages=1))
        client.api.datasets.list.return_value = page

        result = list_datasets(client)

        assert [d["name"] for d in result] == ["beta", "alpha"]  # newest first
        assert result[0]["item_count"] == 8
        assert result[0]["version"] == 2
        assert result[0]["description"] == "desc beta"

    def test_walks_all_pages(self):
        client = MagicMock()
        page1 = MagicMock(
            data=[self._dataset("a", "2026-01-01T00:00:00")],
            meta=MagicMock(total_pages=2),
        )
        page2 = MagicMock(
            data=[self._dataset("b", "2026-01-02T00:00:00")],
            meta=MagicMock(total_pages=2),
        )
        client.api.datasets.list.side_effect = [page1, page2]

        result = list_datasets(client)

        assert {d["name"] for d in result} == {"a", "b"}
        assert client.api.datasets.list.call_count == 2

    def test_empty_project(self):
        client = MagicMock()
        client.api.datasets.list.return_value = MagicMock(
            data=[], meta=MagicMock(total_pages=1)
        )
        assert list_datasets(client) == []

    def test_sync_continues_when_an_item_fails(self):
        """A single bad item is recorded as failed without aborting the sync."""
        client = MagicMock()
        client.get_dataset_runs.return_value = MagicMock(data=[MagicMock()])  # → v2
        client.create_dataset_item.side_effect = [Exception("bad"), None]

        items = [
            {"id": "a", "input": {}, "expected_output": {}, "metadata": {}},
            {"id": "b", "input": {}, "expected_output": {}, "metadata": {}},
        ]

        result = sync_qa_to_langfuse(
            "ds", items, source_url="https://x", langfuse_client=client
        )

        assert result["version"] == 2
        assert result["run_name"] == "v2"
        assert result["created_count"] == 1
        assert result["failed_count"] == 1


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

        dataset, items = prepare_langfuse_dataset(data, "minimal-dataset")

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
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(FileNotFoundError):
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

    def test_base_url_alias(self):
        """LANGFUSE_BASE_URL is accepted as an alias for LANGFUSE_HOST."""
        with patch.dict(
            "os.environ",
            {
                "LANGFUSE_SECRET_KEY": "secret",
                "LANGFUSE_PUBLIC_KEY": "public",
                "LANGFUSE_BASE_URL": "https://langfuse.example.com",
            },
            clear=True,
        ):
            assert is_langfuse_configured() is True
            # The alias is mirrored into LANGFUSE_HOST for the SDK.
            assert os.environ["LANGFUSE_HOST"] == "https://langfuse.example.com"


class TestIsLangfuseAvailable:
    """Tests for is_langfuse_available function."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        # The availability result is memoised process-wide; reset around each
        # test so they don't see each other's cached value.
        reset_langfuse_availability_cache()
        yield
        reset_langfuse_availability_cache()

    def test_available_when_configured_and_credentials_valid(self):
        """Test availability when configured and auth_check passes."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=True
        ):
            with patch("server.services.langfuse.get_client") as mock_get:
                client = MagicMock()
                client.auth_check.return_value = True
                mock_get.return_value = client
                assert is_langfuse_available() is True
                client.auth_check.assert_called_once()

    def test_not_available_when_credentials_rejected(self):
        """Test not available when auth_check rejects the (invalid) keys."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=True
        ):
            with patch("server.services.langfuse.get_client") as mock_get:
                client = MagicMock()
                client.auth_check.return_value = False
                mock_get.return_value = client
                assert is_langfuse_available() is False

    def test_not_available_when_not_configured(self):
        """Test not available when not configured."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=False
        ):
            assert is_langfuse_available() is False

    def test_not_available_when_client_fails(self):
        """Test not available when client initialization fails."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=True
        ):
            with patch("server.services.langfuse.get_client") as mock_get:
                mock_get.side_effect = Exception("Connection failed")
                assert is_langfuse_available() is False

    def test_result_is_memoised(self):
        """auth_check runs once; later calls return the cached result."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=True
        ):
            with patch("server.services.langfuse.get_client") as mock_get:
                client = MagicMock()
                client.auth_check.return_value = True
                mock_get.return_value = client

                assert is_langfuse_available() is True
                assert is_langfuse_available() is True  # cached
                client.auth_check.assert_called_once()

    def test_use_cache_false_forces_recheck(self):
        """use_cache=False bypasses the memoised value."""
        with patch(
            "server.services.langfuse.is_langfuse_configured", return_value=True
        ):
            with patch("server.services.langfuse.get_client") as mock_get:
                client = MagicMock()
                client.auth_check.return_value = True
                mock_get.return_value = client
                assert is_langfuse_available() is True

            # Credentials now rejected — a forced re-check sees the new result.
            with patch("server.services.langfuse.get_client") as mock_get:
                client = MagicMock()
                client.auth_check.return_value = False
                mock_get.return_value = client
                assert is_langfuse_available(use_cache=False) is False


class TestGetDatasetItems:
    """Reading dataset items via the public REST API (Phase 1 of the migration).

    The SDK's typed item model rejects servers without ``media_references``, so
    the service hits the REST endpoint directly; here ``httpx.get`` is mocked.
    """

    @pytest.fixture(autouse=True)
    def _creds(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_HOST", "https://lf.example.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def _rest_item(self, item_id, question, answer, *, status="ACTIVE"):
        # REST payload is camelCase.
        return {
            "id": item_id,
            "status": status,
            "input": {"question": question, "context": "ctx"},
            "expectedOutput": {"answer": answer},
            "metadata": {"version": 1},
            "sourceTraceId": None,
            "datasetId": "ds-id",
            "datasetName": "ds",
            "createdAt": "2026-01-01T00:00:00Z",
        }

    def _response(self, items, total_pages):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"data": items, "meta": {"totalPages": total_pages}}
        return resp

    def test_summarizes_items(self):
        items_page = [
            self._rest_item("h1", "q1", "a1"),
            self._rest_item("h2", "q2", "a2"),
        ]
        with patch(
            "server.services.langfuse.httpx.get",
            return_value=self._response(items_page, 1),
        ) as mock_get:
            items = get_dataset_items("ds")

        assert [i["id"] for i in items] == ["h1", "h2"]
        assert items[0]["input"]["question"] == "q1"
        # camelCase expectedOutput is mapped to snake_case.
        assert items[0]["expected_output"]["answer"] == "a1"
        assert items[0]["status"] == "ACTIVE"
        # Filtered by datasetName, with auth + pagination.
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["datasetName"] == "ds"
        assert kwargs["auth"] == ("pk", "sk")

    def test_walks_all_pages(self):
        pages = [
            self._response([self._rest_item("a", "q", "a")], 2),
            self._response([self._rest_item("b", "q", "a")], 2),
        ]
        with patch("server.services.langfuse.httpx.get", side_effect=pages) as mock_get:
            items = get_dataset_items("ds")

        assert {i["id"] for i in items} == {"a", "b"}
        assert mock_get.call_count == 2

    def test_empty_dataset(self):
        with patch(
            "server.services.langfuse.httpx.get",
            return_value=self._response([], 1),
        ):
            assert get_dataset_items("ds") == []

    def test_raises_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
        with pytest.raises(RuntimeError):
            get_dataset_items("ds")


class TestDeleteDatasetItem:
    @pytest.fixture(autouse=True)
    def _creds(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_HOST", "https://lf.example.com")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def test_calls_rest_delete(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        with patch(
            "server.services.langfuse.httpx.delete", return_value=resp
        ) as mock_delete:
            delete_dataset_item("item-123")

        args, kwargs = mock_delete.call_args
        assert args[0].endswith("/api/public/dataset-items/item-123")
        assert kwargs["auth"] == ("pk", "sk")
