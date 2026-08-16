"""Langfuse-backed dataset reads (Phase 2 of the SoT migration).

These replace the local-SQLite read paths for datasets and Q/A pairs. Datasets
are keyed by their Langfuse **name** (the canonical identifier going forward).
The similarity analyse/clean helpers operate on Langfuse items, deleting
duplicates via the Langfuse delete API.
"""

import json
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from langfuse import get_client

from server.services.langfuse import (
    LangfuseUnavailableError,
    count_dataset_items,
    delete_dataset_item,
    get_dataset_items,
    is_langfuse_available,
    list_dataset_runs,
    list_datasets,
)

logger = logging.getLogger(__name__)


def _require_langfuse() -> None:
    if not is_langfuse_available():
        raise LangfuseUnavailableError(
            "Langfuse is not configured or reachable. Set LANGFUSE_* to read datasets."
        )


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Make a datetime comparable: naive values are read as UTC.

    Langfuse timestamps come back as ISO strings that may or may not carry an
    offset, and comparing an aware datetime to a naive one raises TypeError —
    which would blow up the min/max aggregation in :func:`get_dataset_sources_view`.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _item_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the Q/A fields from a Langfuse dataset item."""
    inp = _as_dict(item.get("input"))
    out = _as_dict(item.get("expected_output"))
    return {
        "id": item.get("id"),
        "question": inp.get("question", ""),
        "answer": out.get("answer", ""),
        "context": inp.get("context", ""),
        "source_url": inp.get("source_url", ""),
        "confidence": out.get("confidence") or 0.0,
        "created_at": _parse_dt(item.get("created_at")),
        "metadata": item.get("metadata") or {},
    }


def _active_items(dataset_name: str) -> List[Dict[str, Any]]:
    return [
        it
        for it in get_dataset_items(dataset_name)
        if (it.get("status") or "ACTIVE") == "ACTIVE"
    ]


# --- dataset list / detail ---------------------------------------------------


def _to_dataset_view(dataset: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dataset.get("metadata") or {}
    return {
        "id": dataset.get("id"),
        "name": dataset.get("name"),
        "description": dataset.get("description"),
        "target_language": metadata.get("target_language"),
        "qa_sources_count": dataset.get("item_count"),
        "created_at": dataset.get("created_at"),
    }


def list_datasets_view() -> List[Dict[str, Any]]:
    """All Langfuse datasets in the DatasetResponse shape.

    The Q/A count comes from the live item count (one cheap request per dataset),
    not the dataset's best-effort ``total_items`` metadata — that metadata is
    stale or absent for datasets created/exported outside the sync path, which
    made the dashboard under-report (or blank) the number of pairs.
    """
    _require_langfuse()
    views = [_to_dataset_view(d) for d in list_datasets()]
    for view in views:
        name = view.get("name")
        if not name:
            continue
        try:
            view["qa_sources_count"] = count_dataset_items(name)
        except Exception as exc:  # noqa: BLE001 — keep the metadata fallback
            logger.warning("Could not count items for dataset '%s': %s", name, exc)
    return views


def get_dataset_view(dataset_name: str) -> Optional[Dict[str, Any]]:
    """A single Langfuse dataset by name, or None if it doesn't exist."""
    _require_langfuse()
    for d in list_datasets():
        if d.get("name") == dataset_name:
            return _to_dataset_view(d)
    return None


# --- create / delete ---------------------------------------------------------


def create_dataset(
    dataset_name: str, description: Optional[str] = None
) -> Dict[str, Any]:
    """Create an empty dataset in Langfuse. Raises ValueError if it exists."""
    _require_langfuse()
    if get_dataset_view(dataset_name) is not None:
        raise ValueError(f"Dataset '{dataset_name}' already exists")
    client = get_client()
    client.create_dataset(
        name=dataset_name,
        description=description or f"Dataset {dataset_name}",
        metadata={"source": "dataset-generator"},
    )
    return {
        "id": dataset_name,
        "name": dataset_name,
        "description": description,
        "message": "Dataset created successfully",
    }


def delete_dataset(dataset_name: str) -> Dict[str, Any]:
    """Delete a dataset's items from Langfuse and drop its Qdrant collection.

    Langfuse has no delete-dataset API (only items/runs), so the empty dataset
    shell remains — every item is deleted and the Qdrant collection dropped, but
    the dataset still appears (with 0 items) until Langfuse adds dataset deletion.
    Raises ValueError when the dataset doesn't exist.
    """
    _require_langfuse()
    if get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    # Delete every item (all statuses, not just ACTIVE).
    deleted = 0
    for item in get_dataset_items(dataset_name):
        delete_dataset_item(item["id"])
        deleted += 1

    # Cascade: drop the Qdrant collection (best-effort, lazy import).
    from server.services.qdrant import delete_collection_for

    qdrant_dropped = delete_collection_for(dataset_name)

    note = " The empty dataset remains in Langfuse (no delete-dataset API)."
    return {
        "message": (
            f"Deleted {deleted} item(s) from '{dataset_name}'"
            + (" and dropped its Qdrant collection." if qdrant_dropped else ".")
            + note
        ),
        "dataset_id": dataset_name,
        "records_deleted": deleted,
    }


# --- sources & analysis history ----------------------------------------------


def _source_label_kind(source_url: str) -> Tuple[str, str]:
    """``(label, kind)`` for a source URL.

    The pipelines record where a pair came from in the item's
    ``input.source_url``: the crawled page URL for the web path, ``file://<name>``
    for an upload, ``github://<user>`` for a GitHub account. The kind drives the
    icon in the UI; the label is the readable form (scheme stripped).
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


def _to_analysis_view(run: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Langfuse run summary to one entry of the analysis history.

    A run is one generation: the seed source that was analysed (the site root
    for a crawl, not the individual pages) plus the stats recorded with it.
    """
    metadata = run.get("metadata") or {}
    source_url = run.get("source_url") or ""
    label, kind = _source_label_kind(source_url)
    exact = metadata.get("exact_duplicates")
    similar = metadata.get("similar_duplicates")
    duplicates = (
        (exact or 0) + (similar or 0)
        if exact is not None or similar is not None
        else None
    )
    return {
        "run_name": run.get("run_name"),
        "version": run.get("version"),
        "source_url": source_url or None,
        "kind": kind,
        "label": label,
        "item_count": run.get("item_count"),
        "pages_analyzed": metadata.get("pages_crawled"),
        "new_pairs": metadata.get("total"),
        "duplicates_skipped": duplicates,
        "created_at": run.get("created_at"),
    }


def get_dataset_sources_view(dataset_name: str) -> Dict[str, Any]:
    """The sources a dataset was built from, plus its analysis history.

    ``sources`` aggregates the dataset's active items by ``input.source_url`` —
    what actually produced Q/A pairs, one entry per crawled page/file/account.
    ``history`` is the run history (one entry per generation), which records the
    *seed* that was analysed and the pairs it yielded. Both come from Langfuse,
    the only persistence layer. Raises ValueError when the dataset doesn't exist.
    """
    _require_langfuse()
    if get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    grouped: Dict[str, Dict[str, Any]] = {}
    total_qa = 0
    for item in _active_items(dataset_name):
        fields = _item_fields(item)
        total_qa += 1
        url = fields["source_url"] or ""
        seen_at = _as_utc(fields["created_at"])
        entry = grouped.get(url)
        if entry is None:
            label, kind = _source_label_kind(url)
            grouped[url] = {
                "url": url or None,
                "kind": kind,
                "label": label,
                "qa_count": 1,
                "first_seen_at": seen_at,
                "last_seen_at": seen_at,
            }
        else:
            entry["qa_count"] += 1
            entry["first_seen_at"] = min(entry["first_seen_at"], seen_at)
            entry["last_seen_at"] = max(entry["last_seen_at"], seen_at)

    sources = sorted(
        grouped.values(), key=lambda s: (-s["qa_count"], s["label"].lower())
    )
    for source in sources:
        source["first_seen_at"] = source["first_seen_at"].isoformat()
        source["last_seen_at"] = source["last_seen_at"].isoformat()

    # A dataset with items but no readable runs is normal (runs are best-effort,
    # see sync_qa_to_langfuse) — show the sources rather than failing the view.
    try:
        runs = list_dataset_runs(dataset_name)
    except LangfuseUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 — history is best-effort
        logger.warning("Could not read runs for dataset '%s': %s", dataset_name, exc)
        runs = []

    history = [_to_analysis_view(run) for run in runs]

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "total_sources": len(sources),
        "total_qa": total_qa,
        "sources": sources,
        "total_analyses": len(history),
        "history": history,
    }


# --- Q/A list ----------------------------------------------------------------


def get_qa_view(
    dataset_name: str, limit: Optional[int] = 10, offset: int = 0
) -> Dict[str, Any]:
    """Paginated Q/A items of a Langfuse dataset (QAListResponse shape).

    Raises ValueError when the dataset doesn't exist.
    """
    _require_langfuse()
    items = _active_items(dataset_name)
    if not items:
        # Distinguish "empty dataset" from "no such dataset".
        if get_dataset_view(dataset_name) is None:
            raise ValueError(f"Dataset '{dataset_name}' not found")

    fields = [_item_fields(it) for it in items]
    # Newest first, matching the previous SQL ordering.
    fields.sort(key=lambda f: f["created_at"], reverse=True)
    total_count = len(fields)
    page = fields[offset : (offset + limit) if limit else None]

    qa_data = [
        {
            "id": f["id"],
            "question": f["question"],
            "answer": f["answer"],
            "context": f["context"],
            "source_url": f["source_url"],
            "confidence": f["confidence"],
            "created_at": f["created_at"],
            "metadata": f["metadata"],
        }
        for f in page
    ]
    return {
        "dataset_name": dataset_name,
        "dataset_id": dataset_name,
        "total_count": total_count,
        "returned_count": len(qa_data),
        "offset": offset,
        "limit": limit,
        "qa_data": qa_data,
    }


# --- Q/A score stats ----------------------------------------------------------


def _raw_confidence(item: Dict[str, Any]) -> Optional[float]:
    """The item's confidence score, or None when it was never scored.

    Unlike ``_item_fields`` (which coerces a missing score to 0.0 for the list
    view), stats must distinguish "scored 0.0" from "not scored" — otherwise
    unscored items would drag the average down and pile into the lowest bucket.
    Reads ``expected_output`` first, then ``metadata`` (where the generation
    sync path stores it).
    """
    out = _as_dict(item.get("expected_output"))
    value = out.get("confidence")
    if value is None:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# Buckets shown on the quality page, highest range first. Each entry is
# (label, predicate) over a confidence score.
_SCORE_BUCKETS = [
    ("0.9–1.0", lambda s: s >= 0.9),
    ("0.8–0.9", lambda s: 0.8 <= s < 0.9),
    ("0.7–0.8", lambda s: 0.7 <= s < 0.8),
    ("< 0.7", lambda s: s < 0.7),
]


def get_qa_stats_view(
    dataset_name: str, score_threshold: float = 0.8
) -> Dict[str, Any]:
    """Aggregate confidence-score stats over every active item of a dataset.

    QAStatsResponse shape. Raises ValueError when the dataset doesn't exist.
    """
    _require_langfuse()
    items = _active_items(dataset_name)
    if not items and get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    scores = [s for s in (_raw_confidence(it) for it in items) if s is not None]
    below = sum(1 for s in scores if s < score_threshold)

    return {
        "dataset_name": dataset_name,
        "dataset_id": dataset_name,
        "total_count": len(items),
        "scored_count": len(scores),
        "average_score": round(sum(scores) / len(scores), 4) if scores else None,
        "score_threshold": score_threshold,
        "below_threshold_count": below,
        "validated_count": len(scores) - below,
        "distribution": [
            {"label": label, "count": sum(1 for s in scores if predicate(s))}
            for label, predicate in _SCORE_BUCKETS
        ],
    }


# --- similarity analyse / clean ----------------------------------------------


def _similar_pairs(fields: List[Dict[str, Any]], threshold: float):
    """Yield (i, j, ratio) for question pairs at or above the threshold."""
    for i, a in enumerate(fields):
        for j in range(i + 1, len(fields)):
            ratio = SequenceMatcher(None, a["question"], fields[j]["question"]).ratio()
            if ratio >= threshold:
                yield i, j, ratio


def analyze_similarities_view(
    dataset_name: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Find near-duplicate questions in a Langfuse dataset (no mutation)."""
    _require_langfuse()
    if get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    fields = [_item_fields(it) for it in _active_items(dataset_name)]

    similarities = []
    for i, j, ratio in _similar_pairs(fields, threshold):
        q1, q2 = fields[i]["question"], fields[j]["question"]
        similarities.append(
            {
                "record1_id": str(fields[i]["id"])[:8],
                "record2_id": str(fields[j]["id"])[:8],
                "similarity": round(ratio, 3),
                "question1": (q1[:100] + "...") if len(q1) > 100 else q1,
                "question2": (q2[:100] + "...") if len(q2) > 100 else q2,
            }
        )

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "threshold": threshold,
        "total_records": len(fields),
        "similar_pairs_found": len(similarities),
        "similarities": sorted(
            similarities, key=lambda x: x["similarity"], reverse=True
        ),
    }


class AmbiguousRecordError(ValueError):
    """A record id prefix matched more than one item."""


def resolve_similarity_pair(dataset_name: str, remove_id: str) -> Dict[str, Any]:
    """Arbitrate one duplicate pair by deleting a single record.

    ``remove_id`` may be the full Langfuse item id or the 8-char prefix the
    analyze view exposes (see ``analyze_similarities_view``, which truncates
    ids for display). A prefix must match exactly one active item; otherwise
    :class:`AmbiguousRecordError` is raised so the caller can ask for the
    full id. Raises ValueError when the dataset or record doesn't exist.
    """
    _require_langfuse()
    if get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    items = _active_items(dataset_name)
    exact = [it for it in items if str(it.get("id", "")) == remove_id]
    matches = exact or [
        it for it in items if str(it.get("id", "")).startswith(remove_id)
    ]
    if not matches:
        raise ValueError(f"Record '{remove_id}' not found in dataset '{dataset_name}'")
    if len(matches) > 1:
        raise AmbiguousRecordError(
            f"Record id '{remove_id}' matches {len(matches)} items — use the full id"
        )

    item = matches[0]
    delete_dataset_item(item["id"])
    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "removed_id": item["id"],
        "removed_question": _item_fields(item)["question"],
    }


def clean_similarities_view(
    dataset_name: str, threshold: float = 0.8
) -> Dict[str, Any]:
    """Remove near-duplicate questions from a Langfuse dataset.

    For each similar pair, keeps the higher-confidence item (ties broken by the
    older creation date) and deletes the other via the Langfuse delete API.
    """
    _require_langfuse()
    if get_dataset_view(dataset_name) is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")

    fields = [_item_fields(it) for it in _active_items(dataset_name)]
    if not fields:
        raise ValueError(f"Dataset '{dataset_name}' has no Q/A pairs")

    details = []
    removed_ids: set[str] = set()
    for i, j, ratio in _similar_pairs(fields, threshold):
        a, b = fields[i], fields[j]
        if a["id"] in removed_ids or b["id"] in removed_ids:
            continue
        # Keep the higher confidence; tie → keep the older item.
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
    for f in fields:
        if f["id"] in removed_ids:
            delete_dataset_item(f["id"])
            removed_items.append(
                {
                    "id": f["id"],
                    "question": f["question"],
                    "similarity": next(
                        d["similarity"]
                        for d in details
                        if d["remove_id"] == str(f["id"])[:8]
                    ),
                    "kept_id": next(
                        d["keep_id"]
                        for d in details
                        if d["remove_id"] == str(f["id"])[:8]
                    ),
                }
            )

    return {
        "dataset_id": dataset_name,
        "dataset_name": dataset_name,
        "threshold": threshold,
        "total_records": len(fields),
        "removed_records": len(removed_ids),
        "details": sorted(details, key=lambda x: x["similarity"], reverse=True),
        "removed_items": removed_items,
    }
