import logging
import time
from typing import Any, Dict, List, Optional, Union
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.dataset import QASource
from server.services.scraper import ScraperService
from server.services.llm import LLMService
from server.services.agent import QAAgentService
from server.services.dataset import DatasetService
from server.services.qa import QAService
from server.services.langfuse import is_langfuse_configured, sync_qa_to_langfuse
from server.schemas.dataset import TargetLanguage


class DatasetPipeline:
    """Pipeline to process a URL and generate a QA dataset"""

    def __init__(self, db: Session):
        self.db = db
        self.scraper_service = ScraperService(db)
        self.llm_service = LLMService()
        self.qa_agent_service = QAAgentService()
        self.dataset_service = DatasetService(db)
        self.qa_service = QAService(db)

    async def process_url(
        self,
        url: str,
        dataset_name: str,
        model_cleaning: Union[str, Any],
        target_language: Union[str, TargetLanguage],
        model_qa: Union[str, Any],
        similarity_threshold: Optional[Union[float, str]] = None,
        crawl: bool = False,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        sync_langfuse: bool = True,
    ) -> Dict[str, Any]:
        """Executes the complete pipeline for a URL.

        When ``crawl`` is true, the seed URL is explored breadth-first
        (same-domain internal links up to ``max_depth``/``max_pages``) and every
        discovered page is cleaned and mined for QA pairs — maximising the
        dataset. When false, only the seed URL is processed (single page).

        After saving, if ``sync_langfuse`` is set and Langfuse is configured, the
        dataset is pushed to Langfuse and a versioned run is recorded.
        """
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

            # Timeline of steps, surfaced to the frontend so the user can follow
            # the pipeline and read a short log line per stage.
            steps: List[Dict[str, Any]] = []

            def record(
                key: str,
                label: str,
                status: str,
                started: float,
                detail: str = "",
                duration_ms: Optional[int] = None,
            ) -> None:
                # ``duration_ms`` lets callers report an accumulated time (e.g. a
                # per-page stage summed across a crawl) instead of a single span.
                steps.append(
                    {
                        "key": key,
                        "label": label,
                        "status": status,
                        "duration_ms": duration_ms
                        if duration_ms is not None
                        else int((time.perf_counter() - started) * 1000),
                        "detail": detail,
                    }
                )

            # 1. Get or create the dataset
            t = time.perf_counter()
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name,
                description=f"Dataset automatically created for {url}",
            )
            record(
                "dataset",
                "Prepare dataset",
                "success",
                t,
                f"Dataset '{dataset_name}' ready",
            )

            # 2. Scrape: a single page, or a breadth-first crawl of the site.
            assert dataset.id is not None
            assert isinstance(dataset.id, str)
            t = time.perf_counter()
            if crawl:
                snapshots = await self.scraper_service.crawl_site(
                    url, dataset.id, max_depth=max_depth, max_pages=max_pages
                )
                record(
                    "scrape",
                    "Crawl site",
                    "success" if snapshots else "warning",
                    t,
                    f"Crawled {len(snapshots)} page(s) from {url}"
                    if snapshots
                    else f"No pages crawled from {url}",
                )
            else:
                snapshots = [await self.scraper_service.scrape_url(url, dataset.id)]
                scraped_len = len(snapshots[0].content or "")
                record(
                    "scrape",
                    "Scrape URL",
                    "success",
                    t,
                    f"Fetched {scraped_len:,} characters from {url}",
                )

            # 3-6. Clean → generate → deduplicate & save, per page. Aggregated so
            # the whole crawl produces one dataset with the maximum of QA pairs.
            qa_list: List[Any] = []
            qa_stats = {"total": 0, "exact_duplicates": 0, "similar_duplicates": 0}
            scraped_chunks: List[str] = []

            # Clean/QA/save are interleaved per page, so we accumulate the time
            # spent in each stage across the whole crawl and report the totals —
            # not a single span (which would make every stage show the full loop).
            clean_s = qa_s = save_s = 0.0
            clean_chars = 0
            for page_snapshot in snapshots:
                assert page_snapshot.id is not None
                page_url = page_snapshot.url
                content = page_snapshot.content or ""
                scraped_chunks.append(f"<!-- {page_url} -->\n{content}")

                # Clean the text with the LLM, then persist it.
                t_stage = time.perf_counter()
                cleaned_text = self.llm_service.clean_text(content, model_cleaning_str)
                clean_chars += len(cleaned_text)
                self.scraper_service.save_cleaned_text(
                    page_snapshot_id=page_snapshot.id,
                    content=cleaned_text,
                    language=target_language_str,
                    model=model_cleaning_str,
                )
                clean_s += time.perf_counter() - t_stage

                # Generate QA pairs for this page.
                t_stage = time.perf_counter()
                page_qa = await self.qa_agent_service.generate_qa(
                    cleaned_text, target_language_str, model_qa_str
                )
                qa_list.extend(page_qa)
                qa_s += time.perf_counter() - t_stage

                # Deduplicate (across the whole dataset) and save.
                t_stage = time.perf_counter()
                page_stats = self.qa_service.process_qa_pairs(
                    qa_list=page_qa,
                    cleaned_text=cleaned_text,
                    url=page_url,
                    page_snapshot_id=page_snapshot.id,
                    dataset_name=dataset_name,
                    model=model_qa_str,
                    dataset_id=dataset.id,
                    similarity_threshold=similarity_threshold,
                )
                save_s += time.perf_counter() - t_stage
                for key in qa_stats:
                    qa_stats[key] += page_stats.get(key, 0)

            record(
                "clean",
                "Clean text",
                "success",
                0,
                f"Cleaned {len(snapshots)} page(s) with {model_cleaning_str} "
                f"→ {clean_chars:,} characters",
                duration_ms=int(clean_s * 1000),
            )
            record(
                "qa",
                "Generate Q&A",
                "success" if qa_list else "warning",
                0,
                f"Generated {len(qa_list)} Q&A pairs with {model_qa_str}"
                if qa_list
                else f"No Q&A pairs generated with {model_qa_str} (check agent/model logs)",
                duration_ms=int(qa_s * 1000),
            )
            record(
                "save",
                "Deduplicate & save",
                "success",
                0,
                f"Saved {qa_stats['total']} pairs · skipped "
                f"{qa_stats['exact_duplicates']} exact and "
                f"{qa_stats['similar_duplicates']} similar duplicates "
                f"(threshold {similarity_threshold})",
                duration_ms=int(save_s * 1000),
            )

            # 7. Version & sync to Langfuse (DVC-like commit) when configured.
            langfuse_result: Optional[Dict[str, Any]] = None
            if sync_langfuse and config.langfuse_auto_sync and is_langfuse_configured():
                t = time.perf_counter()
                try:
                    langfuse_result = self._sync_to_langfuse(
                        dataset_id=dataset.id,
                        dataset_name=dataset_name,
                        source_url=url,
                        stats={**qa_stats, "pages_crawled": len(snapshots)},
                    )
                    record(
                        "langfuse",
                        "Version to Langfuse",
                        "success",
                        t,
                        f"Synced {langfuse_result['total_items']} items as "
                        f"{langfuse_result['run_name']} "
                        f"({langfuse_result['dataset_name']})",
                    )
                except Exception as exc:  # noqa: BLE001 — never fail generation
                    logging.exception("Langfuse sync failed")
                    record(
                        "langfuse",
                        "Version to Langfuse",
                        "warning",
                        t,
                        f"Langfuse sync skipped: {exc}",
                    )

            # 8. Return results
            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset.id,  # Explicitly add the dataset ID to the result
                "pages_crawled": len(snapshots),
                "steps": steps,
                "scraped_content": "\n\n".join(scraped_chunks),
                "langfuse": langfuse_result,
            }

        except Exception as e:
            logging.error(f"Error in dataset pipeline: {str(e)}")
            raise e

    def _sync_to_langfuse(
        self,
        dataset_id: str,
        dataset_name: str,
        source_url: str,
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Push all current QA items for the dataset to Langfuse as a new version."""
        records = (
            self.db.query(QASource).filter(QASource.dataset_id == dataset_id).all()
        )
        items = [record.to_langfuse_dataset_item() for record in records]
        return sync_qa_to_langfuse(
            dataset_name=dataset_name,
            items=items,
            source_url=source_url,
            stats=stats,
        )
