"""Tests for dataset pipeline"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from server.pipelines.dataset import DatasetPipeline
from server.schemas.dataset import TargetLanguage


def _qa_stats(total=0, exact=0, similar=0, items=None):
    return {
        "items": items if items is not None else [],
        "total": total,
        "exact_duplicates": exact,
        "similar_duplicates": similar,
    }


@pytest.fixture
def pipeline():
    """Create a DatasetPipeline instance"""
    return DatasetPipeline()


@pytest.fixture
def mock_qa_service():
    """Patch the QAService class so process_url/file/github don't hit Langfuse.

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
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_url_success(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
        mock_qa_service,
    ):
        """Test successful URL processing pipeline"""
        mock_page = Mock()
        mock_page.url = "https://example.com"
        mock_page.content = "Original scraped content"

        mock_scraper_service = Mock()
        mock_scraper_service.scrape_url = AsyncMock(return_value=mock_page)
        mock_scraper_service_class.return_value = mock_scraper_service

        mock_llm_service = Mock()
        mock_llm_service.clean_text.return_value = "Cleaned text content"
        mock_llm_service_class.return_value = mock_llm_service

        mock_qa_item = Mock()
        mock_qa_item.question = "What is this?"
        mock_qa_item.answer = "This is a test"

        mock_qa_agent_service = Mock()
        mock_qa_agent_service.generate_qa = AsyncMock(return_value=[mock_qa_item])
        mock_qa_agent_service_class.return_value = mock_qa_agent_service

        mock_qa_service.process_qa_pairs.return_value = _qa_stats(total=1)

        pipeline = DatasetPipeline()
        result = await pipeline.process_url(
            url="https://example.com",
            dataset_name="test_dataset",
            model_cleaning="gpt-4o-mini",
            target_language="fr",
            model_qa="gpt-4o-mini",
            similarity_threshold=0.9,
        )

        assert "qa_pairs" in result
        assert "total" in result
        assert "dataset_id" in result
        assert result["dataset_id"] == "test_dataset"
        assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.is_langfuse_available", return_value=False)
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_url_crawl_aggregates_pages(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
        _mock_lf_available,
        mock_qa_service,
    ):
        """With crawl=True, every crawled page is cleaned, mined and aggregated."""
        page1 = Mock(url="https://example.com", content="content 1")
        page2 = Mock(url="https://example.com/a", content="content 2")

        mock_scraper_service = Mock()
        mock_scraper_service.crawl_site = AsyncMock(return_value=[page1, page2])
        mock_scraper_service_class.return_value = mock_scraper_service

        mock_llm_service = Mock()
        mock_llm_service.clean_text.return_value = "cleaned"
        mock_llm_service_class.return_value = mock_llm_service

        mock_qa_item = Mock()
        mock_qa_item.question = "What is this?"
        mock_qa_item.answer = "An answer."
        mock_qa_agent_service = Mock()
        mock_qa_agent_service.generate_qa = AsyncMock(return_value=[mock_qa_item])
        mock_qa_agent_service_class.return_value = mock_qa_agent_service

        mock_qa_service.process_qa_pairs.return_value = _qa_stats(total=1)

        pipeline = DatasetPipeline()
        result = await pipeline.process_url(
            url="https://example.com",
            dataset_name="test_dataset",
            model_cleaning="gpt-4o-mini",
            target_language="fr",
            model_qa="gpt-4o-mini",
            similarity_threshold=0.9,
            crawl=True,
        )

        # One clean / generate / save per crawled page.
        assert mock_llm_service.clean_text.call_count == 2
        assert mock_qa_agent_service.generate_qa.call_count == 2
        assert mock_qa_service.process_qa_pairs.call_count == 2
        mock_scraper_service.crawl_site.assert_awaited_once()

        # Aggregated across both pages.
        assert result["pages_crawled"] == 2
        assert result["total"] == 2
        assert len(result["qa_pairs"]) == 2
        assert result["langfuse"] is None  # Langfuse not configured → skipped

    @pytest.mark.asyncio
    async def test_process_url_default_similarity_threshold(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test that default similarity threshold is applied when None"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock(content="content")
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text", return_value="c"):
                with patch.object(
                    pipeline.qa_agent_service, "generate_qa", AsyncMock(return_value=[])
                ):
                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold=None,
                    )
                    assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    async def test_process_url_invalid_similarity_threshold_type(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test handling of invalid similarity threshold type"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "Test content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned text"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_gen_qa.return_value = []

                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold="invalid",  # Invalid type
                    )

                    # Should convert to default value when invalid
                    assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    async def test_process_url_out_of_range_similarity_threshold(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test clamping of out-of-range similarity threshold"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "Test content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned text"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_gen_qa.return_value = []

                    # Test value > 1.0
                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold=1.5,
                    )
                    assert result["similarity_threshold"] == 1.0

                    # Test value < 0.0
                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset2",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold=-0.5,
                    )
                    assert result["similarity_threshold"] == 0.0

    @pytest.mark.asyncio
    async def test_process_url_with_enum_parameters(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test processing with enum parameters instead of strings"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_gen_qa.return_value = []

                    await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language=TargetLanguage.fr,
                        model_qa="gpt-4o-mini",
                    )

                    # Verify enum values were converted to strings
                    assert mock_clean.call_args[0][1] == "gpt-4o-mini"
                    assert mock_gen_qa.call_args[0][1] == "fr"

    @pytest.mark.asyncio
    async def test_process_url_scraping_error(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test handling of scraping errors"""
        with patch.object(
            pipeline.scraper_service,
            "scrape_url",
            side_effect=Exception("Scraping failed"),
        ):
            with pytest.raises(Exception, match="Scraping failed"):
                await pipeline.process_url(
                    url="https://example.com",
                    dataset_name="test_dataset",
                    model_cleaning="gpt-4o-mini",
                    target_language="fr",
                    model_qa="gpt-4o-mini",
                )

    @pytest.mark.asyncio
    async def test_process_url_llm_cleaning_error(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test handling of LLM cleaning errors"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(
                pipeline.llm_service,
                "clean_text",
                side_effect=Exception("LLM error"),
            ):
                with pytest.raises(Exception, match="LLM error"):
                    await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                    )

    @pytest.mark.asyncio
    async def test_process_url_qa_generation_error(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test handling of QA generation errors"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned"

                with patch.object(
                    pipeline.qa_agent_service,
                    "generate_qa",
                    side_effect=Exception("QA generation failed"),
                ):
                    with pytest.raises(Exception, match="QA generation failed"):
                        await pipeline.process_url(
                            url="https://example.com",
                            dataset_name="test_dataset",
                            model_cleaning="gpt-4o-mini",
                            target_language="fr",
                            model_qa="gpt-4o-mini",
                        )

    @pytest.mark.asyncio
    async def test_process_url_uses_dataset_name_as_id(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """The response's dataset_id is the dataset name (Langfuse is keyed by name,
        there's no local row/id to create anymore)."""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock(content="content")
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text", return_value="c"):
                with patch.object(
                    pipeline.qa_agent_service, "generate_qa", AsyncMock(return_value=[])
                ):
                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="brand_new_dataset",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                    )
                    assert result["dataset_id"] == "brand_new_dataset"

    @pytest.mark.asyncio
    async def test_process_url_complete_flow(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test complete flow from URL to QA pairs"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "Raw content from web page"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "Cleaned and formatted content"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_qa1 = Mock()
                    mock_qa1.question = "Q1?"
                    mock_qa1.answer = "A1"
                    mock_qa2 = Mock()
                    mock_qa2.question = "Q2?"
                    mock_qa2.answer = "A2"
                    mock_gen_qa.return_value = [mock_qa1, mock_qa2]

                    mock_qa_service.process_qa_pairs.return_value = _qa_stats(total=2)

                    result = await pipeline.process_url(
                        url="https://example.com/article",
                        dataset_name="complete_flow_test",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold=0.85,
                    )

                    # Verify all services were called
                    mock_scrape.assert_called_once()
                    mock_clean.assert_called_once_with(
                        "Raw content from web page", "gpt-4o-mini"
                    )
                    mock_gen_qa.assert_called_once_with(
                        "Cleaned and formatted content", "fr", "gpt-4o-mini"
                    )
                    mock_qa_service.process_qa_pairs.assert_called_once()

                    # Verify result
                    assert result["total"] == 2
                    assert result["similarity_threshold"] == 0.85
                    assert len(result["qa_pairs"]) == 2

    @pytest.mark.asyncio
    async def test_process_url_with_invalid_string_similarity_threshold(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test processing with invalid string similarity threshold"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_gen_qa.return_value = []

                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_invalid_string",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold="not-a-number",
                    )
                    # Should use default 0.9
                    assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    async def test_process_url_with_none_similarity_threshold(
        self, pipeline: DatasetPipeline, mock_qa_service
    ):
        """Test processing with None similarity threshold"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned"

                with patch.object(
                    pipeline.qa_agent_service, "generate_qa"
                ) as mock_gen_qa:
                    mock_gen_qa.return_value = []

                    result = await pipeline.process_url(
                        url="https://example.com",
                        dataset_name="test_none",
                        model_cleaning="gpt-4o-mini",
                        target_language="fr",
                        model_qa="gpt-4o-mini",
                        similarity_threshold=None,
                    )
                    # Should use default 0.9
                    assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.file_to_page_images")
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_file_success(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
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
            sync_langfuse=False,
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
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_file_skips_pages_without_text(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
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
            sync_langfuse=False,
        )

        # Only the readable page produced QA; the empty page was skipped.
        assert mock_qa_agent_service_class.return_value.generate_qa.call_count == 1
        assert result["pages_crawled"] == 2  # still reflects all pages read
        assert result["total"] == 1

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.fetch_account_docs")
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.QAAgentService")
    async def test_process_github_success(
        self,
        mock_qa_agent_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
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
            sync_langfuse=False,
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
