import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union
from sqlalchemy.orm import Session

from server.core.config import config
from server.models.dataset import QASource
from server.services.files import file_to_page_images
from server.services.github import fetch_account_docs
from server.services.scraper import ScraperService
from server.services.llm import LLMService
from server.services.agent import QAAgentService
from server.services.dataset import DatasetService
from server.services.qa import QAService
from server.services.langfuse import is_langfuse_available, sync_qa_to_langfuse
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
        crawl_delay_seconds: Optional[float] = None,
        max_pages_per_domain: Optional[int] = None,
        sync_langfuse: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
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
                # Stream the step live (no-op when not streaming).
                if on_progress is not None:
                    on_progress({"type": "step", "step": steps[-1]})

            # 1. Get or create the dataset
            t = time.perf_counter()
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name,
                description=f"Dataset automatically created for {url}",
                target_language=target_language_str,
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
                on_page: Optional[Callable[[Dict[str, Any]], None]] = None
                if on_progress is not None:
                    progress = on_progress

                    def on_page(info: Dict[str, Any]) -> None:
                        progress({"type": "page", **info})

                snapshots = await self.scraper_service.crawl_site(
                    url,
                    dataset.id,
                    max_depth=max_depth,
                    max_pages=max_pages,
                    delay_seconds=crawl_delay_seconds,
                    max_pages_per_domain=max_pages_per_domain,
                    on_page=on_page,
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

            # 7. Version & sync to Langfuse (DVC-like commit) when available.
            # Gating on availability (memoised auth_check) — not just configured
            # — means an invalid/unreachable key is detected once, not retried
            # noisily on every generation.
            langfuse_result: Optional[Dict[str, Any]] = None
            if sync_langfuse and config.langfuse_auto_sync and is_langfuse_available():
                t = time.perf_counter()
                try:
                    langfuse_result = self._sync_to_langfuse(
                        dataset_id=dataset.id,
                        dataset_name=dataset_name,
                        source_url=url,
                        stats={**qa_stats, "pages_crawled": len(snapshots)},
                        target_language=target_language_str,
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

    async def process_file(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        dataset_name: str,
        target_language: Union[str, TargetLanguage],
        model_qa: Union[str, Any],
        model_vlm: Optional[Union[str, Any]] = None,
        similarity_threshold: Optional[Union[float, str]] = None,
        sync_langfuse: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from an uploaded file (PDF or image).

        The file is rasterised to one image per page and transcribed with the
        configured vision model; each page's text is then mined for QA pairs and
        deduplicated/saved exactly like :meth:`process_url` — minus scraping and
        crawling. ``QASource`` rows are saved with a ``file://<name>`` source and
        no page snapshot (the column is nullable).
        """
        try:
            similarity_threshold = self._normalize_threshold(similarity_threshold)

            target_language_str = str(
                target_language.value
                if hasattr(target_language, "value")
                else target_language
            )
            model_qa_str = str(
                model_qa.value if hasattr(model_qa, "value") else model_qa
            )
            model_vlm_str = (
                str(model_vlm.value if hasattr(model_vlm, "value") else model_vlm)
                if model_vlm
                else None
            )
            source_url = f"file://{filename}"

            steps: List[Dict[str, Any]] = []

            def record(
                key: str,
                label: str,
                status: str,
                started: float,
                detail: str = "",
                duration_ms: Optional[int] = None,
            ) -> None:
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
                if on_progress is not None:
                    on_progress({"type": "step", "step": steps[-1]})

            # 1. Get or create the dataset.
            t = time.perf_counter()
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name,
                description=f"Dataset automatically created for {filename}",
                target_language=target_language_str,
            )
            assert dataset.id is not None
            record(
                "dataset",
                "Prepare dataset",
                "success",
                t,
                f"Dataset '{dataset_name}' ready",
            )

            # 2. Rasterise the file to one image per page.
            t = time.perf_counter()
            page_images = file_to_page_images(content, content_type, filename)
            record(
                "rasterize",
                "Read file",
                "success",
                t,
                f"Prepared {len(page_images)} page(s) from {filename}",
            )

            # 3-5. Transcribe each page with the VLM, generate QA, deduplicate &
            # save. Times are accumulated per stage across all pages (like crawl).
            qa_list: List[Any] = []
            qa_stats = {"total": 0, "exact_duplicates": 0, "similar_duplicates": 0}
            extracted_chunks: List[str] = []
            extract_s = qa_s = save_s = 0.0
            extract_chars = 0

            for label, image_bytes, mime_type in page_images:
                t_stage = time.perf_counter()
                text = self.llm_service.extract_text_from_image(
                    image_bytes, mime_type=mime_type, model=model_vlm_str
                )
                extract_s += time.perf_counter() - t_stage
                if not text:
                    continue
                extract_chars += len(text)
                extracted_chunks.append(f"<!-- {label} -->\n{text}")

                t_stage = time.perf_counter()
                page_qa = await self.qa_agent_service.generate_qa(
                    text, target_language_str, model_qa_str
                )
                qa_list.extend(page_qa)
                qa_s += time.perf_counter() - t_stage

                t_stage = time.perf_counter()
                page_stats = self.qa_service.process_qa_pairs(
                    qa_list=page_qa,
                    cleaned_text=text,
                    url=source_url,
                    page_snapshot_id=None,
                    dataset_name=dataset_name,
                    model=model_qa_str,
                    dataset_id=dataset.id,
                    similarity_threshold=similarity_threshold,
                )
                save_s += time.perf_counter() - t_stage
                for key in qa_stats:
                    qa_stats[key] += page_stats.get(key, 0)

            record(
                "extract",
                "Transcribe pages",
                "success" if extract_chars else "warning",
                0,
                f"Transcribed {len(extracted_chunks)} page(s) "
                f"→ {extract_chars:,} characters"
                if extract_chars
                else "No readable text found in the file",
                duration_ms=int(extract_s * 1000),
            )
            record(
                "qa",
                "Generate Q&A",
                "success" if qa_list else "warning",
                0,
                f"Generated {len(qa_list)} Q&A pairs with {model_qa_str}"
                if qa_list
                else f"No Q&A pairs generated with {model_qa_str}",
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

            # 6. Version & sync to Langfuse when available (same gate as the URL path).
            langfuse_result: Optional[Dict[str, Any]] = None
            if sync_langfuse and config.langfuse_auto_sync and is_langfuse_available():
                t = time.perf_counter()
                try:
                    langfuse_result = self._sync_to_langfuse(
                        dataset_id=dataset.id,
                        dataset_name=dataset_name,
                        source_url=source_url,
                        stats={**qa_stats, "pages_crawled": len(page_images)},
                        target_language=target_language_str,
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

            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset.id,
                "pages_crawled": len(page_images),
                "steps": steps,
                "scraped_content": "\n\n".join(extracted_chunks),
                "langfuse": langfuse_result,
            }

        except Exception as e:
            logging.error(f"Error in file pipeline: {str(e)}")
            raise e

    async def process_github(
        self,
        *,
        username: str,
        token: Optional[str] = None,
        dataset_name: str,
        model_cleaning: Union[str, Any],
        target_language: Union[str, TargetLanguage],
        model_qa: Union[str, Any],
        max_repos: Optional[int] = None,
        similarity_threshold: Optional[Union[float, str]] = None,
        sync_langfuse: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from a GitHub account's public documentation.

        Fetches each public repo's README and top-level docs, then cleans →
        generates QA → deduplicates/saves per document, exactly like
        :meth:`process_url` (minus scraping). The token, if given, only raises the
        GitHub API rate limit — only public data is read. ``QASource`` rows are
        saved with a ``github://<user>`` source and no page snapshot.
        """
        try:
            similarity_threshold = self._normalize_threshold(similarity_threshold)

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
            source_url = f"github://{username}"

            steps: List[Dict[str, Any]] = []

            def record(
                key: str,
                label: str,
                status: str,
                started: float,
                detail: str = "",
                duration_ms: Optional[int] = None,
            ) -> None:
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
                if on_progress is not None:
                    on_progress({"type": "step", "step": steps[-1]})

            # 1. Get or create the dataset.
            t = time.perf_counter()
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name,
                description=f"Dataset automatically created for github.com/{username}",
                target_language=target_language_str,
            )
            assert dataset.id is not None
            record(
                "dataset",
                "Prepare dataset",
                "success",
                t,
                f"Dataset '{dataset_name}' ready",
            )

            # 2. Fetch the account's public README + top-level docs.
            t = time.perf_counter()
            docs = fetch_account_docs(username, token=token, max_repos=max_repos)
            record(
                "fetch",
                "Fetch GitHub docs",
                "success" if docs else "warning",
                t,
                f"Fetched {len(docs)} document(s) from github.com/{username}"
                if docs
                else f"No public docs found for github.com/{username}",
            )

            # 3-5. Clean → generate QA → deduplicate & save, per document.
            qa_list: List[Any] = []
            qa_stats = {"total": 0, "exact_duplicates": 0, "similar_duplicates": 0}
            fetched_chunks: List[str] = []
            clean_s = qa_s = save_s = 0.0
            clean_chars = 0

            for label, raw_text in docs:
                t_stage = time.perf_counter()
                cleaned_text = self.llm_service.clean_text(
                    raw_text, model_cleaning_str
                )
                clean_chars += len(cleaned_text)
                fetched_chunks.append(f"<!-- {label} -->\n{cleaned_text}")
                clean_s += time.perf_counter() - t_stage

                t_stage = time.perf_counter()
                doc_qa = await self.qa_agent_service.generate_qa(
                    cleaned_text, target_language_str, model_qa_str
                )
                qa_list.extend(doc_qa)
                qa_s += time.perf_counter() - t_stage

                t_stage = time.perf_counter()
                doc_stats = self.qa_service.process_qa_pairs(
                    qa_list=doc_qa,
                    cleaned_text=cleaned_text,
                    url=source_url,
                    page_snapshot_id=None,
                    dataset_name=dataset_name,
                    model=model_qa_str,
                    dataset_id=dataset.id,
                    similarity_threshold=similarity_threshold,
                )
                save_s += time.perf_counter() - t_stage
                for key in qa_stats:
                    qa_stats[key] += doc_stats.get(key, 0)

            record(
                "clean",
                "Clean text",
                "success",
                0,
                f"Cleaned {len(docs)} document(s) with {model_cleaning_str} "
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
                else f"No Q&A pairs generated with {model_qa_str}",
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

            # 6. Version & sync to Langfuse when available (same gate as the URL path).
            langfuse_result: Optional[Dict[str, Any]] = None
            if sync_langfuse and config.langfuse_auto_sync and is_langfuse_available():
                t = time.perf_counter()
                try:
                    langfuse_result = self._sync_to_langfuse(
                        dataset_id=dataset.id,
                        dataset_name=dataset_name,
                        source_url=source_url,
                        stats={**qa_stats, "pages_crawled": len(docs)},
                        target_language=target_language_str,
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

            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset.id,
                "pages_crawled": len(docs),
                "steps": steps,
                "scraped_content": "\n\n".join(fetched_chunks),
                "langfuse": langfuse_result,
            }

        except Exception as e:
            logging.error(f"Error in github pipeline: {str(e)}")
            raise e

    @staticmethod
    def _normalize_threshold(
        similarity_threshold: Optional[Union[float, str]],
    ) -> float:
        """Coerce a float|str|None threshold into a valid float in [0.0, 1.0]."""
        if isinstance(similarity_threshold, str):
            try:
                similarity_threshold = float(similarity_threshold)
            except ValueError:
                similarity_threshold = None
        if similarity_threshold is None:
            return 0.9
        try:
            value = float(similarity_threshold)
        except (TypeError, ValueError):
            return 0.9
        return max(0.0, min(1.0, value))

    def _sync_to_langfuse(
        self,
        dataset_id: str,
        dataset_name: str,
        source_url: str,
        stats: Dict[str, Any],
        target_language: Optional[str] = None,
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
            target_language=target_language,
        )
