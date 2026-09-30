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
    """Patch the QAService class so process_file/process_url don't hit the store.

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
        mock_llm_service_class.return_value.extract_text_from_image = AsyncMock(
            side_effect=["text from page one", "text from page two"]
        )
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
        mock_llm_service_class.return_value.extract_text_from_image = AsyncMock(
            side_effect=["", "real text"]  # page 1 has no readable text
        )
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


class TestProcessUrl:
    @pytest.fixture
    def page(self):
        from server.services.web import Page

        with patch("server.pipelines.dataset.fetch_page") as fetch:
            fetch.return_value = Page(
                url="https://docs.example.com/guide",
                body="<html><body><nav>menu</nav><h1>Guide</h1>"
                "<p>Install it with make.</p></body></html>",
                content_type="text/html; charset=utf-8",
            )
            yield fetch

    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_fetch_clean_generate(
        self, agent_class, llm_class, page, mock_qa_service
    ):
        llm_class.return_value.clean_text = AsyncMock(
            return_value="Guide. Install it with make."
        )
        agent_class.return_value.generate_qa = AsyncMock(return_value=["qa1"])
        mock_qa_service.process_qa_pairs.return_value = _qa_stats(total=1)

        result = await DatasetPipeline().process_url(
            url="https://docs.example.com/guide",
            dataset_name="ds",
            target_language="en",
            model_cleaning="openai:clean",
            model_qa="claude:claude-sonnet-5",
            persist=False,
        )

        raw, model = llm_class.return_value.clean_text.call_args.args
        assert "Install it with make." in raw and "menu" not in raw
        assert model == "openai:clean"
        text, lang, qa_model = agent_class.return_value.generate_qa.call_args.args
        assert (text, lang, qa_model) == (
            "Guide. Install it with make.",
            "en",
            "claude:claude-sonnet-5",
        )
        assert mock_qa_service.process_qa_pairs.call_args.kwargs["url"] == (
            "https://docs.example.com/guide"
        )
        assert [s["key"] for s in result["steps"]] == ["fetch", "clean", "qa", "save"]
        assert result["total"] == 1 and result["pages_crawled"] == 1

    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_empty_page_generates_nothing(
        self, agent_class, llm_class, page, mock_qa_service
    ):
        from server.services.web import Page

        page.return_value = Page("https://x.dev", "<script>x()</script>", "text/html")
        llm_class.return_value.clean_text = AsyncMock()
        agent_class.return_value.generate_qa = AsyncMock()

        result = await DatasetPipeline().process_url(
            url="https://x.dev",
            dataset_name="ds",
            target_language="en",
            model_cleaning="openai:c",
            model_qa="openai:q",
            persist=False,
        )
        llm_class.return_value.clean_text.assert_not_called()
        agent_class.return_value.generate_qa.assert_not_called()
        assert result["steps"][0]["status"] == "warning"
        assert result["total"] == 0
