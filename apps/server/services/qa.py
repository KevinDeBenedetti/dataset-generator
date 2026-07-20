import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from server.services.dedup import QAEntry, classify_duplicate, compute_hash_from_content
from server.services.langfuse import get_dataset_items
from server.services.quality_rules import rejection_reason


class QAService:
    """Deduplicates generated QA pairs against a dataset's existing items.

    The dedup pool is the target dataset's *existing Langfuse items*, loaded
    once (lazily) per pipeline run — scoped to this one dataset, not global,
    since Langfuse has no cheap "every item across every dataset" read. Grown
    in place after each :meth:`process_qa_pairs` call so a later call (e.g.
    the next crawled page) sees this call's additions.

    When ``quality_rules`` is provided (see
    ``server.services.quality_rules.get_quality_rules``) and its
    ``auto_reject_enabled`` flag is on, pairs failing the rules (answer too
    short, confidence too low) are rejected before deduplication.

    This service only classifies and shapes QA pairs; it writes nothing
    anywhere — the caller is responsible for syncing the returned items to
    Langfuse (see ``DatasetPipeline._sync_to_langfuse``).
    """

    def __init__(
        self, dataset_name: str, quality_rules: Optional[Dict[str, Any]] = None
    ):
        self.dataset_name = dataset_name
        self.quality_rules = quality_rules or {}
        self._existing_entries: Optional[List[QAEntry]] = None

    def _load_existing_entries(self) -> List[QAEntry]:
        if self._existing_entries is None:
            try:
                items = get_dataset_items(self.dataset_name)
            except Exception:  # noqa: BLE001 — new dataset, or Langfuse unreachable
                items = []
            self._existing_entries = [
                QAEntry(
                    hash=item.get("id", ""),
                    question=(item.get("input") or {}).get("question", ""),
                    context=(item.get("input") or {}).get("context", ""),
                    source_url=(item.get("input") or {}).get("source_url", ""),
                )
                for item in items
                if (item.get("status") or "ACTIVE") == "ACTIVE"
            ]
        return self._existing_entries

    def process_qa_pairs(
        self,
        qa_list: List[Any],
        cleaned_text: str,
        url: str,
        model: str,
        similarity_threshold: float = 0.9,
    ) -> Dict[str, Any]:
        """Classify `qa_list` against the in-memory pool.

        Candidates are checked only against the pool as it stood at the start
        of this call — not against siblings added earlier in the same
        ``qa_list``, matching the previous DB-backed behaviour. Returns the
        surviving (non-duplicate) items in Langfuse dataset-item shape,
        alongside per-call stats.
        """
        existing = self._load_existing_entries()
        new_items: List[Dict[str, Any]] = []
        new_entries: List[QAEntry] = []
        exact_duplicates = 0
        similar_duplicates = 0
        quality_rejected = 0

        for qa_item in qa_list:
            question = qa_item.question
            answer = qa_item.answer
            confidence = getattr(qa_item, "confidence", 1.0)

            # Quality rules first (cheaper than dedup classification); no-op
            # unless auto_reject_enabled is set in the provided rules.
            reason = rejection_reason(answer, confidence, self.quality_rules)
            if reason is not None:
                quality_rejected += 1
                logging.info(f"Rejected QA pair by quality rules: {reason}")
                continue

            item_hash = compute_hash_from_content(question, answer, cleaned_text, url)

            candidate = QAEntry(
                hash=item_hash,
                question=question,
                context=cleaned_text,
                source_url=url,
            )
            verdict = classify_duplicate(candidate, existing, similarity_threshold)

            if verdict.type == "exact":
                exact_duplicates += 1
                dup_id_str = (
                    str(verdict.duplicate_hash)[:8]
                    if verdict.duplicate_hash
                    else "unknown"
                )
                logging.info(f"Exact duplicate found (ID: {dup_id_str}...), skipping")

            elif verdict.type == "similar":
                similar_duplicates += 1
                dup_id_str = (
                    str(verdict.duplicate_hash)[:8]
                    if verdict.duplicate_hash
                    else "unknown"
                )
                logging.info(
                    f"Similar question found (similarity: {verdict.similarity_score:.2f}, ID: {dup_id_str}...), skipping"
                )

            else:  # new
                new_items.append(
                    {
                        "id": item_hash,
                        "input": {
                            "question": question,
                            "context": cleaned_text,
                            "source_url": url,
                        },
                        "expected_output": {
                            "answer": answer,
                            "confidence": float(confidence),
                        },
                        "metadata": {
                            "model": model,
                            "generation_timestamp": datetime.now(
                                timezone.utc
                            ).isoformat(),
                            "context_length": len(cleaned_text) if cleaned_text else 0,
                            "question_length": len(question),
                            "answer_length": len(answer),
                            "content_hash": item_hash,
                        },
                    }
                )
                new_entries.append(candidate)

        existing.extend(new_entries)

        logging.info(
            f"Added {len(new_items)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates, "
            f"rejected {quality_rejected} by quality rules"
        )

        return {
            "items": new_items,
            "total": len(new_items),
            "exact_duplicates": exact_duplicates,
            "similar_duplicates": similar_duplicates,
            "quality_rejected": quality_rejected,
        }
