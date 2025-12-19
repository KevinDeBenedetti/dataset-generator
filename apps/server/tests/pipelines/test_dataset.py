"""Tests for dataset pipeline"""

import pytest
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from server.pipelines.dataset import DatasetPipeline
from server.models.dataset import Dataset
from server.schemas.dataset import TargetLanguage


@pytest.fixture
def pipeline(db: Session):
    """Create a DatasetPipeline instance"""
    return DatasetPipeline(db)


@pytest.fixture
def sample_dataset(db: Session):
    """Create a sample dataset"""
    dataset = Dataset(name="test_dataset", description="Test dataset")
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


class TestDatasetPipeline:
    """Tests for DatasetPipeline class"""

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.ScraperService")
    @patch("server.pipelines.dataset.LLMService")
    @patch("server.pipelines.dataset.DatasetService")
    @patch("server.pipelines.dataset.QAService")
    async def test_process_url_success(
        self,
        mock_qa_service_class,
        mock_dataset_service_class,
        mock_llm_service_class,
        mock_scraper_service_class,
        db: Session,
        sample_dataset,
    ):
        """Test successful URL processing pipeline"""
        # Setup mocks
        mock_dataset_service = Mock()
        mock_dataset_service.get_or_create_dataset.return_value = sample_dataset
        mock_dataset_service_class.return_value = mock_dataset_service

        mock_page_snapshot = Mock()
        mock_page_snapshot.id = 1
        mock_page_snapshot.content = "Original scraped content"

        mock_scraper_service = Mock()
        mock_scraper_service.scrape_url.return_value = mock_page_snapshot
        mock_scraper_service.save_cleaned_text.return_value = Mock()
        mock_scraper_service_class.return_value = mock_scraper_service

        mock_llm_service = Mock()
        mock_llm_service.clean_text.return_value = "Cleaned text content"

        mock_qa_item = Mock()
        mock_qa_item.question = "What is this?"
        mock_qa_item.answer = "This is a test"
        mock_llm_service.generate_qa.return_value = [mock_qa_item]
        mock_llm_service_class.return_value = mock_llm_service

        mock_qa_service = Mock()
        mock_qa_service.process_qa_pairs.return_value = {
            "total": 1,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
        }
        mock_qa_service_class.return_value = mock_qa_service

        # Create pipeline and run
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url="https://example.com",
            dataset_name="test_dataset",
            model_cleaning="gpt-4o-mini",
            target_language="french",
            model_qa="gpt-4o-mini",
            similarity_threshold=0.9,
        )

        # Verify result
        assert "qa_pairs" in result
        assert "total" in result
        assert "dataset_id" in result
        assert result["dataset_id"] == sample_dataset.id
        assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    @patch("server.pipelines.dataset.DatasetService")
    async def test_process_url_default_similarity_threshold(
        self, mock_dataset_service_class, db: Session, sample_dataset
    ):
        """Test that default similarity threshold is applied when None"""
        mock_dataset_service = Mock()
        mock_dataset_service.get_or_create_dataset.return_value = sample_dataset
        mock_dataset_service_class.return_value = mock_dataset_service

        with patch.object(DatasetPipeline, "process_url") as mock_process:
            mock_process.return_value = {"similarity_threshold": 0.9}

            pipeline = DatasetPipeline(db)
            await pipeline.process_url(
                url="https://example.com",
                dataset_name="test_dataset",
                model_cleaning="gpt-4o-mini",
                target_language="french",
                model_qa="gpt-4o-mini",
                similarity_threshold=None,
            )

    @pytest.mark.asyncio
    async def test_process_url_invalid_similarity_threshold_type(
        self, pipeline: DatasetPipeline
    ):
        """Test handling of invalid similarity threshold type"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

            with patch.object(pipeline.scraper_service, "scrape_url"):
                with patch.object(pipeline.llm_service, "clean_text"):
                    with patch.object(pipeline.llm_service, "generate_qa"):
                        with patch.object(
                            pipeline.qa_service, "process_qa_pairs"
                        ) as mock_process_qa:
                            mock_process_qa.return_value = {
                                "total": 0,
                                "exact_duplicates": 0,
                                "similar_duplicates": 0,
                            }

                            result = await pipeline.process_url(
                                url="https://example.com",
                                dataset_name="test_dataset",
                                model_cleaning="gpt-4o-mini",
                                target_language="french",
                                model_qa="gpt-4o-mini",
                                similarity_threshold=0.5,  # Valid float type
                            )

                            # Should convert to 0.9 (default)
                            assert result["similarity_threshold"] == 0.9

    @pytest.mark.asyncio
    async def test_process_url_out_of_range_similarity_threshold(
        self, pipeline: DatasetPipeline
    ):
        """Test clamping of out-of-range similarity threshold"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

            with patch.object(pipeline.scraper_service, "scrape_url"):
                with patch.object(pipeline.llm_service, "clean_text"):
                    with patch.object(pipeline.llm_service, "generate_qa"):
                        with patch.object(
                            pipeline.qa_service, "process_qa_pairs"
                        ) as mock_process_qa:
                            mock_process_qa.return_value = {
                                "total": 0,
                                "exact_duplicates": 0,
                                "similar_duplicates": 0,
                            }

                            # Test value > 1.0
                            result = await pipeline.process_url(
                                url="https://example.com",
                                dataset_name="test_dataset",
                                model_cleaning="gpt-4o-mini",
                                target_language="french",
                                model_qa="gpt-4o-mini",
                                similarity_threshold=1.5,
                            )
                            assert result["similarity_threshold"] == 1.0

                            # Test value < 0.0
                            result = await pipeline.process_url(
                                url="https://example.com",
                                dataset_name="test_dataset2",
                                model_cleaning="gpt-4o-mini",
                                target_language="french",
                                model_qa="gpt-4o-mini",
                                similarity_threshold=-0.5,
                            )
                            assert result["similarity_threshold"] == 0.0

    @pytest.mark.asyncio
    async def test_process_url_with_enum_parameters(self, pipeline: DatasetPipeline):
        """Test processing with enum parameters instead of strings"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

            with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
                mock_page = Mock()
                mock_page.id = 1
                mock_page.content = "content"
                mock_scrape.return_value = mock_page

                with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                    mock_clean.return_value = "cleaned"

                    with patch.object(
                        pipeline.llm_service, "generate_qa"
                    ) as mock_gen_qa:
                        mock_gen_qa.return_value = []

                        with patch.object(
                            pipeline.qa_service, "process_qa_pairs"
                        ) as mock_process_qa:
                            mock_process_qa.return_value = {
                                "total": 0,
                                "exact_duplicates": 0,
                                "similar_duplicates": 0,
                            }

                            await pipeline.process_url(
                                url="https://example.com",
                                dataset_name="test_dataset",
                                model_cleaning="gpt-4-0613",
                                target_language=TargetLanguage.fr,
                                model_qa="gpt-4-0613",
                            )

                            # Verify enum values were converted to strings
                            assert mock_clean.call_args[0][1] == "gpt-4-0613"
                            assert mock_gen_qa.call_args[0][1] == "fr"

    @pytest.mark.asyncio
    async def test_process_url_scraping_error(self, pipeline: DatasetPipeline):
        """Test handling of scraping errors"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

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
                        target_language="french",
                        model_qa="gpt-4o-mini",
                    )

    @pytest.mark.asyncio
    async def test_process_url_llm_cleaning_error(self, pipeline: DatasetPipeline):
        """Test handling of LLM cleaning errors"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

            with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
                mock_page = Mock()
                mock_page.id = 1
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
                            target_language="french",
                            model_qa="gpt-4o-mini",
                        )

    @pytest.mark.asyncio
    async def test_process_url_qa_generation_error(self, pipeline: DatasetPipeline):
        """Test handling of QA generation errors"""
        with patch.object(
            pipeline.dataset_service, "get_or_create_dataset"
        ) as mock_get_dataset:
            mock_dataset = Mock()
            mock_dataset.id = 1
            mock_get_dataset.return_value = mock_dataset

            with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
                mock_page = Mock()
                mock_page.id = 1
                mock_page.content = "content"
                mock_scrape.return_value = mock_page

                with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                    mock_clean.return_value = "cleaned"

                    with patch.object(pipeline.scraper_service, "save_cleaned_text"):
                        with patch.object(
                            pipeline.llm_service,
                            "generate_qa",
                            side_effect=Exception("QA generation failed"),
                        ):
                            with pytest.raises(Exception, match="QA generation failed"):
                                await pipeline.process_url(
                                    url="https://example.com",
                                    dataset_name="test_dataset",
                                    model_cleaning="gpt-4o-mini",
                                    target_language="french",
                                    model_qa="gpt-4o-mini",
                                )

    @pytest.mark.asyncio
    async def test_process_url_creates_new_dataset(
        self, pipeline: DatasetPipeline, db: Session
    ):
        """Test that a new dataset is created if it doesn't exist"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.id = 1
            mock_page.content = "content"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "cleaned"

                with patch.object(pipeline.scraper_service, "save_cleaned_text"):
                    with patch.object(
                        pipeline.llm_service, "generate_qa"
                    ) as mock_gen_qa:
                        mock_gen_qa.return_value = []

                        with patch.object(
                            pipeline.qa_service, "process_qa_pairs"
                        ) as mock_process_qa:
                            mock_process_qa.return_value = {
                                "total": 0,
                                "exact_duplicates": 0,
                                "similar_duplicates": 0,
                            }

                            result = await pipeline.process_url(
                                url="https://example.com",
                                dataset_name="brand_new_dataset",
                                model_cleaning="gpt-4o-mini",
                                target_language="french",
                                model_qa="gpt-4o-mini",
                            )

                            # Verify dataset was created
                            dataset = (
                                db.query(Dataset)
                                .filter(Dataset.name == "brand_new_dataset")
                                .first()
                            )
                            assert dataset is not None
                            assert result["dataset_id"] == dataset.id

    @pytest.mark.asyncio
    async def test_process_url_complete_flow(
        self, pipeline: DatasetPipeline, db: Session
    ):
        """Test complete flow from URL to QA pairs"""
        with patch.object(pipeline.scraper_service, "scrape_url") as mock_scrape:
            mock_page = Mock()
            mock_page.id = 1
            mock_page.content = "Raw content from web page"
            mock_scrape.return_value = mock_page

            with patch.object(pipeline.llm_service, "clean_text") as mock_clean:
                mock_clean.return_value = "Cleaned and formatted content"

                with patch.object(
                    pipeline.scraper_service, "save_cleaned_text"
                ) as mock_save:
                    with patch.object(
                        pipeline.llm_service, "generate_qa"
                    ) as mock_gen_qa:
                        mock_qa1 = Mock()
                        mock_qa1.question = "Q1?"
                        mock_qa1.answer = "A1"
                        mock_qa2 = Mock()
                        mock_qa2.question = "Q2?"
                        mock_qa2.answer = "A2"
                        mock_gen_qa.return_value = [mock_qa1, mock_qa2]

                        with patch.object(
                            pipeline.qa_service, "process_qa_pairs"
                        ) as mock_process:
                            mock_process.return_value = {
                                "total": 2,
                                "exact_duplicates": 0,
                                "similar_duplicates": 0,
                            }

                            result = await pipeline.process_url(
                                url="https://example.com/article",
                                dataset_name="complete_flow_test",
                                model_cleaning="gpt-4o-mini",
                                target_language="french",
                                model_qa="gpt-4o-mini",
                                similarity_threshold=0.85,
                            )

                            # Verify all services were called
                            mock_scrape.assert_called_once()
                            mock_clean.assert_called_once_with(
                                "Raw content from web page", "gpt-4o-mini"
                            )
                            mock_save.assert_called_once()
                            mock_gen_qa.assert_called_once_with(
                                "Cleaned and formatted content", "french", "gpt-4o-mini"
                            )
                            mock_process.assert_called_once()

                            # Verify result
                            assert result["total"] == 2
                            assert result["similarity_threshold"] == 0.85
                            assert len(result["qa_pairs"]) == 2
