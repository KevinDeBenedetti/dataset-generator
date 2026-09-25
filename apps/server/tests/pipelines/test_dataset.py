"""Tests for dataset pipeline"""

import pytest
from unittest.mock import AsyncMock, patch

from server.pipelines.dataset import DatasetPipeline


def _qa_stats(total=0, exact=0, similar=0, items=None):
    return {
        "items": items if items is not None else [],
        "total": total,
        "exact_duplicates": exact,
        "similar_duplicates": similar,
    }


@pytest.fixture(autouse=True)
def mock_save_generation():
    """Stub the persistence step: these tests are about the pipeline, not the DB."""
    with patch("server.pipelines.dataset.save_generation") as mock_save:
        mock_save.return_value = {
            "dataset_name": "test_dataset",
            "dataset_id": "ds-1",
            "version": 1,
            "run_name": "v1",
            "total_items": 1,
            "created_count": 1,
        }
        yield mock_save


@pytest.fixture
def mock_qa_service():
    """Patch the QAService class so process_file/process_github don't hit the store.

    ``QAService`` is now instantiated per-call inside each ``process_*``
    method (scoped to that call's dataset name), so tests patch the class
    import rather than an instance attribute.
    """
    with patch("server.pipelines.dataset.QAService") as mock_class:
        instance = mock_class.return_value
        instance.process_qa_pairs.return_value = _qa_stats()
        yield instance


class TestDatasetPipeline:
    """Tests for DatasetPipeline class"""

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.file_to_page_images")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_file_success(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_file_to_images,
        mock_qa_service,
    ):
        """process_file transcribes each page, generates QA and aggregates stats."""
        mock_file_to_images.return_value = [
            ("doc.pdf p.1", b"img1", "image/png"),
            ("doc.pdf p.2", b"img2", "image/png"),
        ]
        mock_llm_service_class.return_value.extract_text_from_image.side_effect = [
            "text from page one",
            "text from page two",
        ]
        mock_qa_agent_service_class.return_value.generate_qa = AsyncMock(
            side_effect=[["qa1"], ["qa2", "qa3"]]
        )
        mock_qa_service.process_qa_pairs.side_effect = [
            _qa_stats(total=1),
            _qa_stats(total=2),
        ]

        pipeline = DatasetPipeline()
        result = await pipeline.process_file(
            content=b"pdf-bytes",
            filename="doc.pdf",
            content_type="application/pdf",
            dataset_name="test_dataset",
            target_language="en",
            model_qa="gpt-4o-mini",
            model_vlm="vlm-x",
            similarity_threshold=0.9,
            persist=False,
        )

        assert result["pages_crawled"] == 2
        assert result["total"] == 3
        assert result["qa_pairs"] == ["qa1", "qa2", "qa3"]
        assert result["dataset_id"] == "test_dataset"

        llm_inst = mock_llm_service_class.return_value
        assert llm_inst.extract_text_from_image.call_count == 2
        # The chosen VLM model is threaded through to the extraction call.
        assert llm_inst.extract_text_from_image.call_args.kwargs["model"] == "vlm-x"

        assert mock_qa_service.process_qa_pairs.call_count == 2
        # Saved items use a file:// source.
        save_kwargs = mock_qa_service.process_qa_pairs.call_args.kwargs
        assert save_kwargs["url"] == "file://doc.pdf"

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.file_to_page_images")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_file_skips_pages_without_text(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_file_to_images,
        mock_qa_service,
    ):
        """A page the VLM can't transcribe is skipped (no QA generation/saving)."""
        mock_file_to_images.return_value = [
            ("doc.pdf p.1", b"img1", "image/png"),
            ("doc.pdf p.2", b"img2", "image/png"),
        ]
        mock_llm_service_class.return_value.extract_text_from_image.side_effect = [
            "",  # page 1: no readable text
            "real text",  # page 2
        ]
        mock_qa_agent_service_class.return_value.generate_qa = AsyncMock(
            return_value=["qa1"]
        )
        mock_qa_service.process_qa_pairs.return_value = _qa_stats(total=1)

        pipeline = DatasetPipeline()
        result = await pipeline.process_file(
            content=b"pdf",
            filename="doc.pdf",
            content_type="application/pdf",
            dataset_name="test_dataset",
            target_language="en",
            model_qa="gpt-4o-mini",
            model_vlm="vlm-x",
            persist=False,
        )

        # Only the readable page produced QA; the empty page was skipped.
        assert mock_qa_agent_service_class.return_value.generate_qa.call_count == 1
        assert result["pages_crawled"] == 2  # still reflects all pages read
        assert result["total"] == 1

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.fetch_account_docs")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_github_success(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_fetch_docs,
        mock_qa_service,
    ):
        """process_github cleans each doc, generates QA and aggregates stats."""
        mock_fetch_docs.return_value = [
            ("octocat/repo1:README", "# raw readme one"),
            ("octocat/repo2:README", "# raw readme two"),
        ]
        mock_llm_service_class.return_value.clean_text.side_effect = [
            "clean one",
            "clean two",
        ]
        mock_qa_agent_service_class.return_value.generate_qa = AsyncMock(
            side_effect=[["qa1"], ["qa2", "qa3"]]
        )
        mock_qa_service.process_qa_pairs.side_effect = [
            _qa_stats(total=1),
            _qa_stats(total=2),
        ]

        pipeline = DatasetPipeline()
        result = await pipeline.process_github(
            username="octocat",
            token="tok",
            dataset_name="test_dataset",
            model_cleaning="gpt-4o-mini",
            target_language="en",
            model_qa="gpt-4o-mini",
            persist=False,
        )

        assert result["pages_crawled"] == 2
        assert result["total"] == 3
        assert result["qa_pairs"] == ["qa1", "qa2", "qa3"]
        assert result["dataset_id"] == "test_dataset"
        # The token + username are forwarded to the GitHub fetch.
        mock_fetch_docs.assert_called_once_with("octocat", token="tok", max_repos=None)
        assert mock_llm_service_class.return_value.clean_text.call_count == 2

        save_kwargs = mock_qa_service.process_qa_pairs.call_args.kwargs
        assert save_kwargs["url"] == "github://octocat"
