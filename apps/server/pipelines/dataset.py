import logging
from typing import Any

from sqlalchemy.orm import Session

from server.schemas.dataset import TargetLanguage
from server.services.dataset import DatasetService
from server.services.llm import LLMService
from server.services.qa import QAService
from server.services.scraper import ScraperService


class DatasetPipeline:
    """Pipeline to process a URL and generate a QA dataset"""

    def __init__(self, db: Session):
        self.db = db
        self.scraper_service = ScraperService(db)
        self.llm_service = LLMService()
        self.dataset_service = DatasetService(db)
        self.qa_service = QAService(db)

    async def process_url(
        self,
        url: str,
        dataset_name: str,
        model_cleaning: str | Any,
        target_language: str | TargetLanguage,
        model_qa: str | Any,
        similarity_threshold: float | str | None = None,
    ) -> dict[str, Any]:
        """Executes the complete pipeline for a URL"""
        # Normalize similarity_threshold: accept float or numeric string
        if isinstance(similarity_threshold, str):
            try:
                similarity_threshold = float(similarity_threshold)
            except ValueError:
                # invalid string — set to None (or raise if you prefer)
                similarity_threshold = None

        # use similarity_threshold as a float | None from here on
        try:
            # Validate and set default for similarity_threshold
            if similarity_threshold is None:
                similarity_threshold = 0.9
                logging.warning(
                    "similarity_threshold was None, using default value 0.9"
                )

            # Ensure similarity_threshold is a valid float
            try:
                similarity_threshold = float(similarity_threshold)
            except (TypeError, ValueError):
                logging.error(
                    f"Invalid similarity_threshold value: {similarity_threshold}, using default 0.9"
                )
                similarity_threshold = 0.9

            # Validate threshold range
            if not (0.0 <= similarity_threshold <= 1.0):
                logging.warning(
                    f"similarity_threshold {similarity_threshold} out of range [0.0, 1.0], clamping"
                )
                similarity_threshold = max(0.0, min(1.0, similarity_threshold))

            # Extract string values from enum objects
            model_cleaning_str = str(
                model_cleaning.value
                if hasattr(model_cleaning, "value")
                else model_cleaning
            )
            target_language_str = str(
                target_language.value
                if hasattr(target_language, "value")
                else target_language
            )
            model_qa_str = str(
                model_qa.value if hasattr(model_qa, "value") else model_qa
            )

            logging.info(
                f"Processing URL with similarity_threshold: {similarity_threshold}"
            )

            # 1. Get or create the dataset
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name,
                description=f"Dataset automatically created for {url}",
            )

            # 2. Scrape the URL
            assert dataset.id is not None
            assert isinstance(dataset.id, str)
            page_snapshot = self.scraper_service.scrape_url(url, dataset.id)

            # 3. Clean the text with LLM
            assert page_snapshot.content is not None
            assert isinstance(page_snapshot.content, str)
            cleaned_text = self.llm_service.clean_text(
                page_snapshot.content, model_cleaning_str
            )

            # 4. Save the cleaned text
            assert page_snapshot.id is not None
            assert isinstance(page_snapshot.id, str)
            self.scraper_service.save_cleaned_text(
                page_snapshot_id=page_snapshot.id,
                content=cleaned_text,
                language=target_language_str,
                model=model_cleaning_str,
            )

            # 5. Generate QA pairs
            qa_list = self.llm_service.generate_qa(
                cleaned_text, target_language_str, model_qa_str
            )

            # 6. Process and save QA pairs
            assert dataset.id is not None
            assert isinstance(dataset.id, str)
            qa_stats = self.qa_service.process_qa_pairs(
                qa_list=qa_list,
                cleaned_text=cleaned_text,
                url=url,
                page_snapshot_id=page_snapshot.id,
                dataset_name=dataset_name,
                model=model_qa_str,
                dataset_id=dataset.id,
                similarity_threshold=similarity_threshold,
            )

            # 7. Return results
            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset.id,  # Explicitly add the dataset ID to the result
            }

        except Exception as e:
            logging.error(f"Error in dataset pipeline: {e!s}")
            raise e
