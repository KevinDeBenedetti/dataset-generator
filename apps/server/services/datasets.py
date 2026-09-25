"""Postgres-backed dataset reads and writes.

The single access point for datasets, their Q/A pairs and their run history —
Postgres is the source of truth. Datasets are addressed by their **name**
everywhere: that is what the routes take and what the front-end holds, ids
stay internal.

Every function returns plain dicts in the response schemas' shape, so the API
layer stays a thin error-mapping wrapper.
"""

import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from server.core.database import get_scoped_db
from server.models.dataset import Dataset, DatasetRun, QAPair

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _get_dataset(db: Session, dataset_name: str) -> Optional[Dataset]:
    return db.scalar(select(Dataset).where(Dataset.name == dataset_name))


def _require_dataset(db: Session, dataset_name: str) -> Dataset:
    dataset = _get_dataset(db, dataset_name)
    if dataset is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")
    return dataset


# --- dataset list / detail ---------------------------------------------------


def _to_dataset_view(
    dataset: Dataset, qa_count: int, version: Optional[int] = None
) -> Dict[str, Any]:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "target_language": dataset.target_language,
        "qa_sources_count": qa_count,
        "version": version,
        "created_at": _iso(dataset.created_at),
    }


def list_datasets_view() -> List[Dict[str, Any]]:
    """Every dataset, newest first, with its live Q/A count and version.

    Counts and versions are aggregated in two grouped queries rather than one
    per dataset, so the list costs three round trips whatever the number of
    datasets.
    """
    with get_scoped_db() as db:
        datasets = list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc())))
        counts = dict(
            db.execute(
                select(QAPair.dataset_id, func.count(QAPair.id)).group_by(
                    QAPair.dataset_id
                )
            ).all()
        )
        versions = dict(
            db.execute(
                select(DatasetRun.dataset_id, func.max(DatasetRun.version)).group_by(
                    DatasetRun.dataset_id
                )
            ).all()
        )
        return [
            _to_dataset_view(d, counts.get(d.id, 0), versions.get(d.id))
            for d in datasets
        ]


def get_dataset_view(dataset_name: str) -> Optional[Dict[str, Any]]:
    """A single dataset by name, or None if it doesn't exist."""
    with get_scoped_db() as db:
        dataset = _get_dataset(db, dataset_name)
        if dataset is None:
            return None
        qa_count = (
            db.scalar(
                select(func.count(QAPair.id)).where(QAPair.dataset_id == dataset.id)
            )
            or 0
        )
        version = db.scalar(
            select(func.max(DatasetRun.version)).where(
                DatasetRun.dataset_id == dataset.id
            )
        )
        return _to_dataset_view(dataset, qa_count, version)


# --- create / delete ---------------------------------------------------------


def create_dataset(
    dataset_name: str, description: Optional[str] = None
) -> Dict[str, Any]:
    """Create an empty dataset. Raises ValueError if the name is taken."""
    with get_scoped_db() as db:
        if _get_dataset(db, dataset_name) is not None:
            raise ValueError(f"Dataset '{dataset_name}' already exists")
        dataset = Dataset(name=dataset_name, description=description)
        db.add(dataset)
        db.commit()
        return {
            "id": dataset.id,
            "name": dataset.name,
            "description": dataset.description,
            "message": "Dataset created successfully",
        }


def delete_dataset(dataset_name: str) -> Dict[str, Any]:
    """Delete a dataset, its pairs and its history, and drop its Qdrant collection.

    Raises ValueError when the dataset doesn't exist.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        deleted = (
            db.scalar(
                select(func.count(QAPair.id)).where(QAPair.dataset_id == dataset.id)
            )
            or 0
        )
        # The pairs and runs go with it (FK ON DELETE CASCADE).
        db.delete(dataset)
        db.commit()

    # Cascade outside the DB: drop the Qdrant collection (best-effort, lazy import).
    from server.services.qdrant import delete_collection_for

    qdrant_dropped = delete_collection_for(dataset_name)

    return {
        "message": (
            f"Deleted dataset '{dataset_name}' and its {deleted} Q/A pair(s)"
            + (" and dropped its Qdrant collection." if qdrant_dropped else ".")
        ),
        "dataset_id": dataset_name,
        "records_deleted": deleted,
    }


# --- generation writes -------------------------------------------------------


def next_version(dataset_name: str) -> int:
    """The version number the next run of this dataset gets (1-based)."""
    with get_scoped_db() as db:
        dataset = _get_dataset(db, dataset_name)
        if dataset is None:
            return 1
        current = db.scalar(
            select(func.max(DatasetRun.version)).where(
                DatasetRun.dataset_id == dataset.id
            )
        )
        return (current or 0) + 1


def save_generation(
    dataset_name: str,
    items: List[Dict[str, Any]],
    *,
    source_url: str,
    stats: Optional[Dict[str, Any]] = None,
    target_language: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a generation: upsert the dataset, its new pairs, and one run.

    Called at the end of every pipeline. The dataset is created on first use, so
    generating into a new name just works. Pair ids are content hashes, which
    makes this idempotent: re-running over unchanged content updates the row in
    place instead of duplicating it.

    Returns a summary of the recorded version.
    """
    stats = stats or {}
    with get_scoped_db() as db:
        dataset = _get_dataset(db, dataset_name)
        if dataset is None:
            dataset = Dataset(
                name=dataset_name,
                description=description or f"Generated from {source_url}",
                target_language=target_language,
            )
            db.add(dataset)
            db.flush()
        elif target_language and not dataset.target_language:
            # Only fill a blank: a re-generation must not silently relabel an
            # existing dataset's language.
            dataset.target_language = target_language
        dataset.updated_at = _now()

        version = (
            db.scalar(
                select(func.max(DatasetRun.version)).where(
                    DatasetRun.dataset_id == dataset.id
                )
            )
            or 0
        ) + 1

        saved = 0
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            fields = _pair_fields(item, dataset.id, version)
            existing = db.get(QAPair, item_id)
            if existing is None:
                db.add(QAPair(id=item_id, **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
            saved += 1

        run = DatasetRun(
            dataset_id=dataset.id,
            version=version,
            source_url=source_url,
            item_count=saved,
            pages_analyzed=stats.get("pages_crawled"),
            new_pairs=stats.get("total"),
            duplicates_skipped=(
                (stats.get("exact_duplicates") or 0)
                + (stats.get("similar_duplicates") or 0)
                if "exact_duplicates" in stats or "similar_duplicates" in stats
                else None
            ),
        )
        db.add(run)
        db.commit()

        return {
            "dataset_name": dataset_name,
            "dataset_id": dataset.id,
            "version": version,
            "run_name": f"v{version}",
            "total_items": len(items),
            "created_count": saved,
        }


def _pair_fields(item: Dict[str, Any], dataset_id: str, version: int) -> Dict[str, Any]:
    """Map a pipeline item (see services.qa) onto QAPair columns."""
    metadata = dict(item.get("metadata") or {})
    return {
        "dataset_id": dataset_id,
        "question": item.get("question", ""),
        "answer": item.get("answer", ""),
        "context": item.get("context") or "",
        "source_url": item.get("source_url") or None,
        "confidence": item.get("confidence"),
        "model": metadata.get("model"),
        "version": version,
        "qa_metadata": metadata,
    }


# --- Q/A list ----------------------------------------------------------------


def _to_qa_view(pair: QAPair) -> Dict[str, Any]:
    return {
        "id": pair.id,
        "question": pair.question,
        "answer": pair.answer,
        "context": pair.context,
        "source_url": pair.source_url or "",
        "confidence": pair.confidence or 0.0,
        "created_at": pair.created_at,
        "metadata": pair.qa_metadata or {},
    }


def get_qa_view(
    dataset_name: str, limit: Optional[int] = 10, offset: int = 0
) -> Dict[str, Any]:
    """One page of a dataset's Q/A pairs, newest first (QAListResponse shape).

    Raises ValueError when the dataset doesn't exist.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        total_count = (
            db.scalar(
                select(func.count(QAPair.id)).where(QAPair.dataset_id == dataset.id)
            )
            or 0
        )
        query = (
            select(QAPair)
            .where(QAPair.dataset_id == dataset.id)
            .order_by(QAPair.created_at.desc(), QAPair.id)
            .offset(offset)
        )
        if limit:
            query = query.limit(limit)
        pairs = list(db.scalars(query))

        return {
            "dataset_name": dataset.name,
            "dataset_id": dataset.name,
            "total_count": total_count,
            "returned_count": len(pairs),
            "offset": offset,
            "limit": limit,
            "qa_data": [_to_qa_view(p) for p in pairs],
        }


# --- Q/A score stats ----------------------------------------------------------

# Buckets shown on the quality page, highest range first. Each entry is
# (label, lower bound inclusive, upper bound exclusive).
_SCORE_BUCKETS: List[Tuple[str, float, float]] = [
    ("0.9–1.0", 0.9, 1.01),
    ("0.8–0.9", 0.8, 0.9),
    ("0.7–0.8", 0.7, 0.8),
    ("< 0.7", -1.0, 0.7),
]


def get_qa_stats_view(
    dataset_name: str, score_threshold: float = 0.8
) -> Dict[str, Any]:
    """Confidence-score stats over a dataset (QAStatsResponse shape).

    Pairs generated without a score are counted in ``total_count`` but excluded
    from the average and the buckets — an unscored pair is not a zero-scored
    one, and folding the two together would drag the average down.

    Raises ValueError when the dataset doesn't exist.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        total_count = (
            db.scalar(
                select(func.count(QAPair.id)).where(QAPair.dataset_id == dataset.id)
            )
            or 0
        )
        scores = list(
            db.scalars(
                select(QAPair.confidence).where(
                    QAPair.dataset_id == dataset.id, QAPair.confidence.is_not(None)
                )
            )
        )
        below = sum(1 for s in scores if s < score_threshold)

        return {
            "dataset_name": dataset.name,
            "dataset_id": dataset.name,
            "total_count": total_count,
            "scored_count": len(scores),
            "average_score": round(sum(scores) / len(scores), 4) if scores else None,
            "score_threshold": score_threshold,
            "below_threshold_count": below,
            "validated_count": len(scores) - below,
            "distribution": [
                {
                    "label": label,
                    "count": sum(1 for s in scores if low <= s < high),
                }
                for label, low, high in _SCORE_BUCKETS
            ],
        }


# --- sources & analysis history ----------------------------------------------


def _source_label_kind(source_url: str) -> Tuple[str, str]:
    """``(label, kind)`` for a source URL.

    The pipelines record where a pair came from in ``source_url``: the crawled
    page URL for the web path, ``file://<name>`` for an upload,
    ``github://<user>`` for a GitHub account. The kind drives the icon in the
    UI; the label is the readable form (scheme stripped).
    """
    if not source_url:
        return "Unknown source", "unknown"
    if source_url.startswith("file://"):
        return source_url[len("file://") :] or source_url, "file"
    if source_url.startswith("github://"):
        return source_url[len("github://") :] or source_url, "github"
    if source_url.startswith(("http://", "https://")):
        parsed = urlparse(source_url)
        return (parsed.netloc + parsed.path).rstrip("/") or source_url, "web"
    return source_url, "unknown"


def _to_analysis_view(run: DatasetRun) -> Dict[str, Any]:
    """Map a recorded run to one entry of the analysis history."""
    label, kind = _source_label_kind(run.source_url or "")
    return {
        "run_name": run.run_name,
        "version": run.version,
        "source_url": run.source_url or None,
        "kind": kind,
        "label": label,
        "item_count": run.item_count,
        "pages_analyzed": run.pages_analyzed,
        "new_pairs": run.new_pairs,
        "duplicates_skipped": run.duplicates_skipped,
        "created_at": _iso(run.created_at),
    }


def list_dataset_versions(dataset_name: str) -> Dict[str, Any]:
    """A dataset's version history, newest first.

    Raises ValueError when the dataset doesn't exist.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        runs = list(
            db.scalars(
                select(DatasetRun)
                .where(DatasetRun.dataset_id == dataset.id)
                .order_by(DatasetRun.version.desc())
            )
        )
        versions = [_to_analysis_view(r) for r in runs]
        return {
            "dataset_name": dataset.name,
            "total": len(versions),
            "versions": versions,
        }


def get_dataset_sources_view(dataset_name: str) -> Dict[str, Any]:
    """The sources a dataset was built from, plus its analysis history.

    ``sources`` groups the pairs by ``source_url`` — what actually produced Q/A
    pairs, one entry per crawled page/file/account, aggregated in SQL.
    ``history`` is one entry per recorded generation, which carries the *seed*
    that was analysed rather than the individual pages.

    Raises ValueError when the dataset doesn't exist.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)

        rows = db.execute(
            select(
                QAPair.source_url,
                func.count(QAPair.id),
                func.min(QAPair.created_at),
                func.max(QAPair.created_at),
            )
            .where(QAPair.dataset_id == dataset.id)
            .group_by(QAPair.source_url)
        ).all()

        sources: List[Dict[str, Any]] = []
        total_qa = 0
        for url, count, first_seen, last_seen in rows:
            total_qa += count
            label, kind = _source_label_kind(url or "")
            sources.append(
                {
                    "url": url or None,
                    "kind": kind,
                    "label": label,
                    "qa_count": count,
                    "first_seen_at": _iso(first_seen),
                    "last_seen_at": _iso(last_seen),
                }
            )
        # Busiest source first, then alphabetically.
        sources.sort(key=lambda s: (-int(s["qa_count"]), str(s["label"]).lower()))

        runs = list(
            db.scalars(
                select(DatasetRun)
                .where(DatasetRun.dataset_id == dataset.id)
                .order_by(DatasetRun.version.desc())
            )
        )
        history = [_to_analysis_view(r) for r in runs]

        return {
            "dataset_id": dataset.name,
            "dataset_name": dataset.name,
            "total_sources": len(sources),
            "total_qa": total_qa,
            "sources": sources,
            "total_analyses": len(history),
            "history": history,
        }


# --- similarity analyse / clean ----------------------------------------------


def _similar_pairs(pairs: List[Dict[str, Any]], threshold: float):
    """Yield (i, j, ratio) for question pairs at or above the threshold."""
    for i, a in enumerate(pairs):
        for j in range(i + 1, len(pairs)):
            ratio = SequenceMatcher(None, a["question"], pairs[j]["question"]).ratio()
            if ratio >= threshold:
                yield i, j, ratio


def _pair_dicts(db: Session, dataset: Dataset) -> List[Dict[str, Any]]:
    """The dataset's pairs in the shape the similarity helpers work on."""
    return [
        {
            "id": p.id,
            "question": p.question,
            "confidence": p.confidence or 0.0,
            "created_at": p.created_at,
        }
        for p in db.scalars(select(QAPair).where(QAPair.dataset_id == dataset.id))
    ]


def analyze_similarities_view(
    dataset_name: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Find near-duplicate questions in a dataset (no mutation)."""
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        pairs = _pair_dicts(db, dataset)

    similarities = []
    for i, j, ratio in _similar_pairs(pairs, threshold):
        q1, q2 = pairs[i]["question"], pairs[j]["question"]
        similarities.append(
            {
                "record1_id": str(pairs[i]["id"])[:8],
                "record2_id": str(pairs[j]["id"])[:8],
                "similarity": round(ratio, 3),
                "question1": (q1[:100] + "...") if len(q1) > 100 else q1,
                "question2": (q2[:100] + "...") if len(q2) > 100 else q2,
            }
        )

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "threshold": threshold,
        "total_records": len(pairs),
        "similar_pairs_found": len(similarities),
        "similarities": sorted(
            similarities, key=lambda x: x["similarity"], reverse=True
        ),
    }


class AmbiguousRecordError(ValueError):
    """A record id prefix matched more than one pair."""


def resolve_similarity_pair(dataset_name: str, remove_id: str) -> Dict[str, Any]:
    """Arbitrate one duplicate pair by deleting a single record.

    ``remove_id`` may be the full pair id or the 8-char prefix the analyze view
    exposes (it truncates ids for display). A prefix must match exactly one
    pair; otherwise :class:`AmbiguousRecordError` is raised so the caller can
    ask for the full id. Raises ValueError when the dataset or record is unknown.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        exact = db.scalar(
            select(QAPair).where(
                QAPair.dataset_id == dataset.id, QAPair.id == remove_id
            )
        )
        matches = (
            [exact]
            if exact is not None
            else list(
                db.scalars(
                    select(QAPair).where(
                        QAPair.dataset_id == dataset.id,
                        QAPair.id.startswith(remove_id),
                    )
                )
            )
        )
        if not matches:
            raise ValueError(
                f"Record '{remove_id}' not found in dataset '{dataset_name}'"
            )
        if len(matches) > 1:
            raise AmbiguousRecordError(
                f"Record id '{remove_id}' matches {len(matches)} items — use the full id"
            )

        pair = matches[0]
        removed = {"id": pair.id, "question": pair.question}
        db.delete(pair)
        db.commit()

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "removed_id": removed["id"],
        "removed_question": removed["question"],
    }


def clean_similarities_view(
    dataset_name: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Remove near-duplicate questions from a dataset.

    For each similar pair, keeps the higher-confidence record (ties broken by
    the older creation date) and deletes the other.
    """
    with get_scoped_db() as db:
        dataset = _require_dataset(db, dataset_name)
        pairs = _pair_dicts(db, dataset)
        if not pairs:
            raise ValueError(f"Dataset '{dataset_name}' has no Q/A pairs")

        details = []
        removed_ids: set[str] = set()
        for i, j, ratio in _similar_pairs(pairs, threshold):
            a, b = pairs[i], pairs[j]
            if a["id"] in removed_ids or b["id"] in removed_ids:
                continue
            # Keep the higher confidence; tie → keep the older record.
            if a["confidence"] > b["confidence"]:
                keep, remove = a, b
            elif b["confidence"] > a["confidence"]:
                keep, remove = b, a
            else:
                keep, remove = (a, b) if a["created_at"] <= b["created_at"] else (b, a)

            removed_ids.add(remove["id"])
            details.append(
                {
                    "keep_id": str(keep["id"])[:8],
                    "remove_id": str(remove["id"])[:8],
                    "similarity": round(ratio, 3),
                    "keep_question": keep["question"],
                    "remove_question": remove["question"],
                }
            )

        removed_items = []
        for pair in pairs:
            if pair["id"] not in removed_ids:
                continue
            similarity = next(
                d["similarity"]
                for d in details
                if d["remove_id"] == str(pair["id"])[:8]
            )
            kept_id = next(
                d["keep_id"] for d in details if d["remove_id"] == str(pair["id"])[:8]
            )
            removed_items.append(
                {
                    "id": pair["id"],
                    "question": pair["question"],
                    "similarity": similarity,
                    "kept_id": kept_id,
                }
            )

        if removed_ids:
            db.execute(delete(QAPair).where(QAPair.id.in_(removed_ids)))
            db.commit()

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "threshold": threshold,
        "total_records": len(pairs),
        "removed_records": len(removed_ids),
        "details": sorted(details, key=lambda x: x["similarity"], reverse=True),
        "removed_items": removed_items,
    }


# --- dedup pool / exports -----------------------------------------------------


def get_dataset_pairs(dataset_name: str) -> List[Dict[str, Any]]:
    """Every pair of a dataset, for the dedup pool and the Qdrant sync.

    Returns an empty list for an unknown dataset: both callers treat "nothing
    stored yet" and "no such dataset" the same way (a first generation into a
    new name goes through here before the dataset exists).
    """
    with get_scoped_db() as db:
        dataset = _get_dataset(db, dataset_name)
        if dataset is None:
            return []
        return [
            _to_qa_view(p)
            for p in db.scalars(
                select(QAPair)
                .where(QAPair.dataset_id == dataset.id)
                .order_by(QAPair.created_at.desc(), QAPair.id)
            )
        ]


def duplicate_dataset(
    dataset_name: str, target_name: Optional[str] = None
) -> Dict[str, Any]:
    """Copy a dataset's pairs into another dataset (the export flow).

    Pair ids are content hashes and the primary key is global, so a copy can't
    reuse the source's id: each copied pair gets a stable id derived from the
    source id and the target dataset. That derivation is deterministic, which
    makes re-running the copy idempotent — the second run refreshes the same
    rows instead of failing on a duplicate key.

    Raises ValueError when the source doesn't exist or has no pairs.
    """
    with get_scoped_db() as db:
        source = _require_dataset(db, dataset_name)
        pairs = list(db.scalars(select(QAPair).where(QAPair.dataset_id == source.id)))
        if not pairs:
            raise ValueError(f"Dataset '{dataset_name}' has no Q/A pairs")

        name = target_name or f"{dataset_name}-copy"
        target = _get_dataset(db, name)
        if target is None:
            target = Dataset(
                name=name,
                description=f"Copy of {dataset_name}",
                target_language=source.target_language,
            )
            db.add(target)
            db.flush()

        copied = 0
        for pair in pairs:
            copy_id = (
                pair.id if target.id == source.id else f"{pair.id}-{target.id[:8]}"
            )
            fields = {
                "dataset_id": target.id,
                "question": pair.question,
                "answer": pair.answer,
                "context": pair.context,
                "source_url": pair.source_url,
                "confidence": pair.confidence,
                "model": pair.model,
                "version": pair.version,
                "qa_metadata": pair.qa_metadata,
            }
            existing = db.get(QAPair, copy_id)
            if existing is None:
                db.add(QAPair(id=copy_id, **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
            copied += 1
        db.commit()

        return {
            "message": "Dataset copied successfully",
            "dataset_name": dataset_name,
            "target_dataset_name": name,
            "total_items": len(pairs),
            "created_count": copied,
        }
