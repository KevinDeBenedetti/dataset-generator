import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from server.core.config import config
from server.services.agent import QAAgentService
from server.services.credentials import Credentials
from server.services.datasets import save_generation
from server.services.files import file_to_page_images
from server.services.llm import LLMService
from server.services.qa import QAService
from server.services.quality_rules import get_quality_rules
from server.services.web import fetch_page, html_to_text
from server.schemas.dataset import TargetLanguage

# Question-similarity cut-off when the caller sends none — tuned for the
# embedding comparison (see services/semantic.py), which is the default path.
DEFAULT_SIMILARITY_THRESHOLD = 0.85

ProgressFn = Callable[[Dict[str, Any]], None]


class _Run:
    """Steps and stats of one pipeline run, shared by every source."""

    def __init__(self, on_progress: Optional[ProgressFn]) -> None:
        self.on_progress = on_progress
        self.steps: List[Dict[str, Any]] = []
        self.qa_list: List[Any] = []
        self.items: List[Dict[str, Any]] = []
        self.chunks: List[str] = []
        self.stats = {
            "total": 0,
            "exact_duplicates": 0,
            "similar_duplicates": 0,
            "flagged_for_review": 0,
        }

    def record(
        self,
        key: str,
        label: str,
        status: str,
        started: float,
        detail: str = "",
        duration_ms: Optional[int] = None,
    ) -> None:
        self.steps.append(
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
        if self.on_progress is not None:
            self.on_progress({"type": "step", "step": self.steps[-1]})


def _value(v: Union[str, Any]) -> str:
    """Enum members (TargetLanguage…) and plain strings alike."""
    return str(v.value if hasattr(v, "value") else v)


class DatasetPipeline:
    """Generate a QA dataset from an uploaded file or a web page.

    Model arguments are references (``"<provider>:<model>"``, see
    services/providers), resolved by the caller. PostgreSQL is the persistence
    layer (see ``_persist``): if that step is skipped or fails, the generated
    pairs are still returned in the response but nothing is stored
    server-side for later retrieval.
    """

    def __init__(self, owner_id: str, creds: Credentials):
        # Everything this pipeline reads or writes belongs to this user: the
        # dedup pool, the quality rules, and the dataset the pairs land in.
        self.owner_id = owner_id
        self.llm_service = LLMService(creds)
        self.qa_agent_service = QAAgentService(creds)

    async def process_file(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        dataset_name: str,
        target_language: Union[str, TargetLanguage],
        model_qa: str,
        model_vlm: str,
        similarity_threshold: Optional[Union[float, str]] = None,
        persist: bool = True,
        on_progress: Optional[ProgressFn] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from an uploaded file (PDF or image).

        The file is rasterised to one image per page and transcribed with the
        vision model; each page's text is then mined for QA pairs (see
        :meth:`_mine`). Pairs are stored with a ``file://<name>`` source.
        """
        run = _Run(on_progress)
        source_url = f"file://{filename}"
        qa_service = await self._qa_service(dataset_name)

        # 1. Rasterise the file to one image per page.
        t = time.perf_counter()
        page_images = file_to_page_images(content, content_type, filename)
        run.record(
            "rasterize",
            "Read file",
            "success",
            t,
            f"Prepared {len(page_images)} page(s) from {filename}",
        )

        # 2. Transcribe each page with the vision model.
        t = time.perf_counter()
        texts: List[Tuple[str, str]] = []
        for label, image_bytes, mime_type in page_images:
            text = await self.llm_service.extract_text_from_image(
                image_bytes, mime_type=mime_type, model=model_vlm
            )
            if text:
                texts.append((label, text))
        chars = sum(len(text) for _, text in texts)
        run.record(
            "extract",
            "Transcribe pages",
            "success" if chars else "warning",
            t,
            f"Transcribed {len(texts)} page(s) with {model_vlm} → {chars:,} characters"
            if chars
            else "No readable text found in the file",
        )

        return await self._mine_and_save(
            run,
            texts,
            qa_service,
            dataset_name=dataset_name,
            source_url=source_url,
            target_language=_value(target_language),
            model_qa=model_qa,
            similarity_threshold=similarity_threshold,
            persist=persist,
            pages=len(page_images),
        )

    async def process_url(
        self,
        *,
        url: str,
        dataset_name: str,
        target_language: Union[str, TargetLanguage],
        model_cleaning: str,
        model_qa: str,
        similarity_threshold: Optional[Union[float, str]] = None,
        persist: bool = True,
        on_progress: Optional[ProgressFn] = None,
    ) -> Dict[str, Any]:
        """Generate a QA dataset from one web page (no crawling).

        The page is fetched (see services/web.py for the SSRF/size guards),
        reduced to text, cleaned by the ``model_cleaning`` model, then mined
        for QA pairs. Pairs are stored with the page URL as their source.
        """
        run = _Run(on_progress)
        qa_service = await self._qa_service(dataset_name)

        # 1. Fetch the page and strip it to text.
        t = time.perf_counter()
        page = await fetch_page(url)
        raw_text = html_to_text(page.body) if page.is_html else page.body
        run.record(
            "fetch",
            "Fetch page",
            "success" if raw_text.strip() else "warning",
            t,
            f"Fetched {page.url} → {len(raw_text):,} characters of text",
        )

        # 2. Clean it (drops leftover navigation, boilerplate).
        t = time.perf_counter()
        cleaned = (
            await self.llm_service.clean_text(raw_text, model_cleaning)
            if raw_text.strip()
            else ""
        )
        run.record(
            "clean",
            "Clean text",
            "success" if cleaned else "warning",
            t,
            f"Cleaned with {model_cleaning} → {len(cleaned):,} characters"
            if cleaned
            else "No text left to mine on this page",
        )

        return await self._mine_and_save(
            run,
            [(page.url, cleaned)] if cleaned else [],
            qa_service,
            dataset_name=dataset_name,
            source_url=page.url,
            target_language=_value(target_language),
            model_qa=model_qa,
            similarity_threshold=similarity_threshold,
            persist=persist,
            pages=1,
        )

    async def _qa_service(self, dataset_name: str) -> QAService:
        qa_service = QAService(
            self.owner_id,
            dataset_name,
            quality_rules=get_quality_rules(self.owner_id),
        )
        # DB read + embedding model load + one pass over the dataset's
        # questions: off the event loop.
        await asyncio.to_thread(qa_service.prepare)
        return qa_service

    async def _mine_and_save(
        self,
        run: _Run,
        texts: List[Tuple[str, str]],
        qa_service: QAService,
        *,
        dataset_name: str,
        source_url: str,
        target_language: str,
        model_qa: str,
        similarity_threshold: Optional[Union[float, str]],
        persist: bool,
        pages: int,
    ) -> Dict[str, Any]:
        """Generate QA per text, deduplicate, persist — the steps every source shares."""
        threshold = self._normalize_threshold(similarity_threshold)
        qa_s = save_s = 0.0
        for label, text in texts:
            run.chunks.append(f"<!-- {label} -->\n{text}")

            t = time.perf_counter()
            text_qa = await self.qa_agent_service.generate_qa(
                text, target_language, model_qa
            )
            run.qa_list.extend(text_qa)
            qa_s += time.perf_counter() - t

            t = time.perf_counter()
            text_stats = qa_service.process_qa_pairs(
                qa_list=text_qa,
                cleaned_text=text,
                url=source_url,
                model=model_qa,
                similarity_threshold=threshold,
            )
            save_s += time.perf_counter() - t
            run.items.extend(text_stats["items"])
            for key in run.stats:
                run.stats[key] += text_stats.get(key, 0)

        stats = run.stats
        run.record(
            "qa",
            "Generate Q&A",
            "success" if run.qa_list else "warning",
            0,
            f"Generated {len(run.qa_list)} Q&A pairs with {model_qa}"
            if run.qa_list
            else f"No Q&A pairs generated with {model_qa}",
            duration_ms=int(qa_s * 1000),
        )
        run.record(
            "save",
            "Deduplicate",
            "success",
            0,
            f"Kept {stats['total']} pairs · skipped "
            f"{stats['exact_duplicates']} exact and "
            f"{stats['similar_duplicates']} similar duplicates "
            f"(threshold {threshold})"
            + (
                f" · {stats['flagged_for_review']} flagged for review"
                if stats["flagged_for_review"]
                else ""
            ),
            duration_ms=int(save_s * 1000),
        )

        persist_result: Optional[Dict[str, Any]] = None
        if persist and config.persist_datasets:
            t = time.perf_counter()
            try:
                persist_result = self._persist(
                    dataset_name=dataset_name,
                    items=run.items,
                    source_url=source_url,
                    stats={**stats, "pages_crawled": pages},
                    target_language=target_language,
                )
                run.record(
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
                run.record(
                    "persist", "Save dataset", "warning", t, f"Dataset not saved: {exc}"
                )

        return {
            "qa_pairs": run.qa_list,
            **stats,
            "similarity_threshold": threshold,
            "dataset_id": dataset_name,
            "pages_crawled": pages,
            "steps": run.steps,
            "scraped_content": "\n\n".join(run.chunks),
            "persisted": persist_result,
        }

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
            return DEFAULT_SIMILARITY_THRESHOLD
        try:
            value = float(similarity_threshold)
        except (TypeError, ValueError):
            return DEFAULT_SIMILARITY_THRESHOLD
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
            self.owner_id,
            dataset_name,
            items,
            source_url=source_url,
            stats=stats,
            target_language=target_language,
        )
