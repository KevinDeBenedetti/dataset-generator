import functools
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from server.core.config import config
from server.services.datasets import get_dataset_pairs
from server.services.dedup import (
    DuplicateVerdict,
    QAEntry,
    classify_duplicate,
    compute_hash_from_content,
    find_exact,
)
from server.services.quality_rules import rejection_reason
from server.services.semantic import (
    Embedder,
    SemanticIndex,
    find_semantic_duplicate,
    get_local_embedder,
    grounding_scores,
    split_sections,
)

# Sentinel: "resolve the process-wide embedder" (None means "explicitly none").
_DEFAULT = object()


class QAService:
    """Deduplicates generated QA pairs against a dataset's existing pairs.

    The dedup pool is the target dataset's *stored pairs*, loaded once (lazily)
    per pipeline run — scoped to this one dataset rather than global, so a run
    reads one dataset's rows instead of the whole table. Grown in place after
    each :meth:`process_qa_pairs` call so a later call (e.g. the next crawled
    page) sees this call's additions.

    With an embedding model (see ``server.services.semantic``), a candidate is
    a *similar* duplicate when its question's cosine to any question of the
    dataset — whatever the source — reaches ``similarity_threshold``, and each
    kept pair gets a ``grounding_score`` (answer ↔ source) in its metadata,
    with ``needs_review`` set below ``config.answer_grounding_threshold``.
    Without one, it falls back to the lexical same-source comparison of
    ``server.services.dedup``.

    When ``quality_rules`` is provided (see
    ``server.services.quality_rules.get_quality_rules``) and its
    ``auto_reject_enabled`` flag is on, pairs failing the rules (answer too
    short, confidence too low) are rejected before deduplication.

    This service only classifies and shapes QA pairs; it writes nothing
    anywhere — the caller is responsible for persisting the returned items
    (see ``DatasetPipeline._persist``).
    """

    def __init__(
        self,
        owner_id: str,
        dataset_name: str,
        quality_rules: Optional[Dict[str, Any]] = None,
        embedder: Any = _DEFAULT,
    ):
        self.owner_id = owner_id
        self.dataset_name = dataset_name
        self.quality_rules = quality_rules or {}
        self._embedder_arg = embedder
        self._existing_entries: Optional[List[QAEntry]] = None
        self._question_index: Optional[SemanticIndex] = None

    @functools.cached_property
    def embedder(self) -> Optional[Embedder]:
        if self._embedder_arg is _DEFAULT:
            return get_local_embedder()
        return self._embedder_arg

    def prepare(self) -> None:
        """Load the pool, the model and the question index up front.

        Blocking (DB read, model load, one embedding batch over the dataset's
        questions): the async pipeline runs it in a worker thread so the event
        loop isn't stalled. Calling it is optional — everything also loads
        lazily on the first :meth:`process_qa_pairs`.
        """
        self._load_existing_entries()
        self._load_question_index()

    def _load_existing_entries(self) -> List[QAEntry]:
        if self._existing_entries is None:
            try:
                pairs = get_dataset_pairs(self.owner_id, self.dataset_name)
            except Exception:  # noqa: BLE001 — DB unreachable: dedup within this run only
                logging.warning(
                    "Could not read existing pairs of '%s' — deduplicating "
                    "against this run only.",
                    self.dataset_name,
                )
                pairs = []
            self._existing_entries = [
                QAEntry(
                    hash=pair.get("id", ""),
                    question=pair.get("question", ""),
                    context=pair.get("context", ""),
                    source_url=pair.get("source_url", ""),
                )
                for pair in pairs
            ]
        return self._existing_entries

    def _load_question_index(self) -> Optional[SemanticIndex]:
        embedder = self.embedder
        if embedder is None:
            return None
        if self._question_index is None:
            index = SemanticIndex()
            questions = [e.question for e in self._load_existing_entries()]
            if questions:
                index.add(questions, embedder.embed(questions))
            self._question_index = index
        return self._question_index

    def _grounding(self, answers: List[str], source_text: str) -> List[Optional[float]]:
        """Answer ↔ closest source chunk cosine per answer (None without a model)."""
        embedder = self.embedder
        if embedder is None or not answers:
            return [None] * len(answers)
        chunks = split_sections(source_text) or (
            [source_text] if source_text.strip() else []
        )
        if not chunks:
            return [None] * len(answers)
        scores = grounding_scores(embedder.embed(answers), embedder.embed(chunks))
        return [round(float(s), 3) for s in scores]

    def process_qa_pairs(
        self,
        qa_list: List[Any],
        cleaned_text: str,
        url: str,
        model: str,
        similarity_threshold: float = 0.9,
    ) -> Dict[str, Any]:
        """Classify `qa_list` against the in-memory pool.

        Lexically, candidates are checked only against the pool as it stood at
        the start of this call — not against siblings added earlier in the same
        ``qa_list``, matching the previous DB-backed behaviour. Semantically,
        an accepted candidate joins the index at once, so a rephrasing of it
        later in the same batch is caught too. Returns the surviving
        (non-duplicate) items in the shape the store expects, alongside
        per-call stats.
        """
        existing = self._load_existing_entries()
        index = self._load_question_index()
        embedder = self.embedder

        # Quality rules first (cheaper than dedup classification); no-op
        # unless auto_reject_enabled is set in the provided rules.
        candidates: List[Any] = []
        quality_rejected = 0
        for qa_item in qa_list:
            confidence = getattr(qa_item, "confidence", 1.0)
            reason = rejection_reason(qa_item.answer, confidence, self.quality_rules)
            if reason is not None:
                quality_rejected += 1
                logging.info(f"Rejected QA pair by quality rules: {reason}")
                continue
            candidates.append(qa_item)

        # One embedding batch for the whole call rather than one per pair.
        question_vectors = (
            embedder.embed([qa.question for qa in candidates])
            if index is not None and embedder is not None and candidates
            else None
        )

        new_items: List[Dict[str, Any]] = []
        new_entries: List[QAEntry] = []
        exact_duplicates = 0
        similar_duplicates = 0

        for i, qa_item in enumerate(candidates):
            question = qa_item.question
            answer = qa_item.answer
            confidence = getattr(qa_item, "confidence", 1.0)

            item_hash = compute_hash_from_content(question, answer, cleaned_text, url)

            candidate = QAEntry(
                hash=item_hash,
                question=question,
                context=cleaned_text,
                source_url=url,
            )
            if index is not None and question_vectors is not None:
                verdict = self._classify_semantic(
                    candidate,
                    existing,
                    new_entries,
                    index,
                    question_vectors[i],
                    similarity_threshold,
                )
            else:
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
                if index is not None and question_vectors is not None:
                    index.add([question], question_vectors[i : i + 1])
                new_items.append(
                    {
                        "id": item_hash,
                        "question": question,
                        "answer": answer,
                        "context": cleaned_text,
                        "source_url": url,
                        "confidence": float(confidence),
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

        flagged_for_review = 0
        scores = self._grounding([it["answer"] for it in new_items], cleaned_text)
        for item, score in zip(new_items, scores):
            if score is None:
                continue
            needs_review = score < config.answer_grounding_threshold
            item["metadata"]["grounding_score"] = score
            item["metadata"]["needs_review"] = needs_review
            if needs_review:
                flagged_for_review += 1
                logging.info(
                    "Answer far from its source (grounding %.2f), flagged for "
                    "review: %.80s",
                    score,
                    item["question"],
                )

        logging.info(
            f"Added {len(new_items)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates, "
            f"rejected {quality_rejected} by quality rules, "
            f"flagged {flagged_for_review} for review"
        )

        return {
            "items": new_items,
            "total": len(new_items),
            "exact_duplicates": exact_duplicates,
            "similar_duplicates": similar_duplicates,
            "quality_rejected": quality_rejected,
            "flagged_for_review": flagged_for_review,
        }

    def _classify_semantic(
        self,
        candidate: QAEntry,
        existing: List[QAEntry],
        accepted: List[QAEntry],
        index: SemanticIndex,
        vector: Any,
        threshold: float,
    ) -> DuplicateVerdict:
        """Exact hash first, then question cosine against the whole dataset."""
        exact = find_exact(candidate, existing)
        if exact is not None:
            return DuplicateVerdict("exact", exact, 1.0)
        match = find_semantic_duplicate(vector, index, threshold)
        if match is None:
            return DuplicateVerdict("new", None, 0.0)
        position, score = match
        # Index rows are the pool's entries followed by this call's accepted
        # pairs, in the same order, so a position maps back to its entry.
        if position < len(existing):
            dup_hash = existing[position].hash
        else:
            dup_hash = accepted[position - len(existing)].hash
        return DuplicateVerdict("similar", dup_hash, score)
