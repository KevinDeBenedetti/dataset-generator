import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from server.models.dataset import QASource
from server.services.dedup import QAEntry, classify_duplicate


class QAService:
    def __init__(self, db: Session):
        self.db = db
        # In-memory dedup pool, loaded once (lazily, on first use) instead of
        # once per QA pair. Previously every candidate re-ran `db.query(...).all()`
        # against the whole table; now that's a single load per pipeline run,
        # and comparisons happen in memory via the pure dedup logic. Grown
        # after each process_qa_pairs call's commit (see its docstring) so a
        # later call — e.g. the next crawled page — sees this call's additions.
        self._existing_entries: Optional[List[QAEntry]] = None

    def _load_existing_entries(self) -> List[QAEntry]:
        if self._existing_entries is None:
            self._existing_entries = [
                QASource._to_entry(record) for record in self.db.query(QASource).all()
            ]
        return self._existing_entries

    def process_qa_pairs(
        self,
        qa_list: List[Any],
        cleaned_text: str,
        url: str,
        page_snapshot_id: Optional[str],
        dataset_name: str,
        model: str,
        dataset_id: Optional[str] = None,
        similarity_threshold: float = 0.9,
    ) -> Dict[str, int]:
        """Processes and saves QA pairs, deduplicating against an in-memory pool.

        `QASource` is still written to (it remains the store `/langfuse/export`
        and `/langfuse/preview` read from later) — only the *dedup lookup*
        moved in-memory, so it no longer re-scans the whole table per pair.

        Candidates are checked only against the pool as it stood at the start
        of this call — not against siblings added earlier in the same
        ``qa_list`` — matching the DB session's ``autoflush=False`` (see
        ``core/database.py``): the old ``db.query(...).all()`` lookup never
        saw same-call, not-yet-committed rows either. The pool is extended
        with this call's new entries only after commit, so a *later* call
        (e.g. the next crawled page) does see them.
        """
        existing = self._load_existing_entries()
        qa_records = []
        new_entries: List[QAEntry] = []
        exact_duplicates = 0
        similar_duplicates = 0

        for i, qa_item in enumerate(qa_list):
            candidate = QAEntry(
                hash=QASource.compute_hash_from_content(
                    qa_item.question, qa_item.answer, cleaned_text, url
                ),
                question=qa_item.question,
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
                qa_record = QASource.from_qa_generation(
                    question=qa_item.question,
                    answer=qa_item.answer,
                    context=cleaned_text,
                    confidence=getattr(qa_item, "confidence", 1.0),
                    source_url=url,
                    page_snapshot_id=page_snapshot_id,
                    dataset_id=dataset_id,  # Passage du dataset_id
                    index=i,
                )

                qa_record.dataset_name = dataset_name
                qa_record.model = model
                qa_records.append(qa_record)
                self.db.add(qa_record)
                new_entries.append(candidate)

        self.db.commit()
        existing.extend(new_entries)

        logging.info(
            f"Added {len(qa_records)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates"
        )

        return {
            "total": len(qa_records),
            "exact_duplicates": exact_duplicates,
            "similar_duplicates": similar_duplicates,
        }
