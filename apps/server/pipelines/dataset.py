import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union

from server.core.config import config
from server.services.files import file_to_page_images
from server.services.github import fetch_account_docs
from server.services.llm import LLMService
from server.services.agent import QAAgentService
from server.services.qa import QAService
from server.services.quality_rules import get_quality_rules
from server.services.datasets import save_generation
from server.schemas.dataset import TargetLanguage


class DatasetPipeline:
    """Pipeline to process an uploaded file or a GitHub account and generate a
    QA dataset.

    PostgreSQL is the persistence layer (see ``_persist``): if that step is
    skipped or fails, the generated pairs are still returned in the response
    but nothing is stored server-side for later retrieval.
    """

    def __init__(self):
        self.llm_service = LLMService()
        self.qa_agent_service = QAAgentService()

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
        persist: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from an uploaded file (PDF or image).

        The file is rasterised to one image per page and transcribed with the
        configured vision model; each page's text is then mined for QA pairs and
        deduplicated exactly like :meth:`process_url` — minus scraping and
        crawling. Pairs are stored with a ``file://<name>`` source.
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

            qa_service = QAService(dataset_name, quality_rules=get_quality_rules())

            # 1. Rasterise the file to one image per page.
            t = time.perf_counter()
            page_images = file_to_page_images(content, content_type, filename)
            record(
                "rasterize",
                "Read file",
                "success",
                t,
                f"Prepared {len(page_images)} page(s) from {filename}",
            )

            # 2-4. Transcribe each page with the VLM, generate QA, deduplicate.
            # Times are accumulated per stage across all pages (like crawl).
            qa_list: List[Any] = []
            qa_stats = {"total": 0, "exact_duplicates": 0, "similar_duplicates": 0}
            saved_items: List[Dict[str, Any]] = []
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
                page_stats = qa_service.process_qa_pairs(
                    qa_list=page_qa,
                    cleaned_text=text,
                    url=source_url,
                    model=model_qa_str,
                    similarity_threshold=similarity_threshold,
                )
                save_s += time.perf_counter() - t_stage
                saved_items.extend(page_stats["items"])
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
                "Deduplicate",
                "success",
                0,
                f"Kept {qa_stats['total']} pairs · skipped "
                f"{qa_stats['exact_duplicates']} exact and "
                f"{qa_stats['similar_duplicates']} similar duplicates "
                f"(threshold {similarity_threshold})",
                duration_ms=int(save_s * 1000),
            )

            # 5. Persist and version the run (same gate as the URL path).
            persist_result: Optional[Dict[str, Any]] = None
            if persist and config.persist_datasets:
                t = time.perf_counter()
                try:
                    persist_result = self._persist(
                        dataset_name=dataset_name,
                        items=saved_items,
                        source_url=source_url,
                        stats={**qa_stats, "pages_crawled": len(page_images)},
                        target_language=target_language_str,
                    )
                    record(
                        "persist",
                        "Save dataset",
                        "success",
                        t,
                        f"Saved {persist_result['created_count']} pair(s) as "
                        f"{persist_result['run_name']} "
                        f"({persist_result['dataset_name']})",
                    )
                except Exception as exc:  # noqa: BLE001 — never fail generation
                    logging.exception("Saving the dataset failed")
                    record(
                        "persist",
                        "Save dataset",
                        "warning",
                        t,
                        f"Dataset not saved: {exc}",
                    )

            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset_name,
                "pages_crawled": len(page_images),
                "steps": steps,
                "scraped_content": "\n\n".join(extracted_chunks),
                "persisted": persist_result,
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
        persist: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from a GitHub account's public documentation.

        Fetches each public repo's README and top-level docs, then cleans →
        generates QA → deduplicates per document, exactly like
        :meth:`process_url` (minus scraping). The token, if given, only raises the
        GitHub API rate limit — only public data is read. Items are synced to
        stored with a ``github://<user>`` source.
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

            qa_service = QAService(dataset_name, quality_rules=get_quality_rules())

            # 1. Fetch the account's public README + top-level docs.
            t = time.perf_counter()
            docs = await fetch_account_docs(username, token=token, max_repos=max_repos)
            record(
                "fetch",
                "Fetch GitHub docs",
                "success" if docs else "warning",
                t,
                f"Fetched {len(docs)} document(s) from github.com/{username}"
                if docs
                else f"No public docs found for github.com/{username}",
            )

            # 2-4. Clean → generate QA → deduplicate, per document.
            qa_list: List[Any] = []
            qa_stats = {"total": 0, "exact_duplicates": 0, "similar_duplicates": 0}
            saved_items: List[Dict[str, Any]] = []
            fetched_chunks: List[str] = []
            clean_s = qa_s = save_s = 0.0
            clean_chars = 0

            for label, raw_text in docs:
                t_stage = time.perf_counter()
                cleaned_text = self.llm_service.clean_text(raw_text, model_cleaning_str)
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
                doc_stats = qa_service.process_qa_pairs(
                    qa_list=doc_qa,
                    cleaned_text=cleaned_text,
                    url=source_url,
                    model=model_qa_str,
                    similarity_threshold=similarity_threshold,
                )
                save_s += time.perf_counter() - t_stage
                saved_items.extend(doc_stats["items"])
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
                "Deduplicate",
                "success",
                0,
                f"Kept {qa_stats['total']} pairs · skipped "
                f"{qa_stats['exact_duplicates']} exact and "
                f"{qa_stats['similar_duplicates']} similar duplicates "
                f"(threshold {similarity_threshold})",
                duration_ms=int(save_s * 1000),
            )

            # 5. Persist and version the run (same gate as the URL path).
            persist_result: Optional[Dict[str, Any]] = None
            if persist and config.persist_datasets:
                t = time.perf_counter()
                try:
                    persist_result = self._persist(
                        dataset_name=dataset_name,
                        items=saved_items,
                        source_url=source_url,
                        stats={**qa_stats, "pages_crawled": len(docs)},
                        target_language=target_language_str,
                    )
                    record(
                        "persist",
                        "Save dataset",
                        "success",
                        t,
                        f"Saved {persist_result['created_count']} pair(s) as "
                        f"{persist_result['run_name']} "
                        f"({persist_result['dataset_name']})",
                    )
                except Exception as exc:  # noqa: BLE001 — never fail generation
                    logging.exception("Saving the dataset failed")
                    record(
                        "persist",
                        "Save dataset",
                        "warning",
                        t,
                        f"Dataset not saved: {exc}",
                    )

            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold,
                "dataset_id": dataset_name,
                "pages_crawled": len(docs),
                "steps": steps,
                "scraped_content": "\n\n".join(fetched_chunks),
                "persisted": persist_result,
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

    def _persist(
        self,
        dataset_name: str,
        items: List[Dict[str, Any]],
        source_url: str,
        stats: Dict[str, Any],
        target_language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store this run's new QA pairs as a new version of the dataset.

        Pair ids are content hashes (see ``compute_hash_from_content``), so
        this stays idempotent across re-runs even though it only writes the
        pairs generated in *this* call, not a full re-read of the dataset.
        """
        return save_generation(
            dataset_name,
            items,
            source_url=source_url,
            stats=stats,
            target_language=target_language,
        )
