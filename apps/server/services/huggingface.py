"""Export a stored dataset to the Hugging Face Hub, as a private dataset repo.

Postgres stays the source of truth; the Hub is an export target. One export
writes two files to the repo:

* ``data/train.jsonl`` — one Q/A pair per line, the format fine-tuning tooling
  and the Hub's dataset viewer both read directly;
* ``README.md`` — a dataset card whose front matter points the viewer at that
  file and records where the data came from.

**Everything published here is private.** The repo is created with
``private=True`` and there is deliberately no way to ask for a public one: a
generated dataset carries scraped source text and the account's own content.
The one case that could leak is an *existing* repo — ``create_repo`` documents
that ``private`` "is ignored if the repo already exists" — so a repo that is
already public makes the export fail (:class:`HuggingFaceRepoPublicError`)
instead of uploading into it.
"""

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from server.core.config import config
from server.services.datasets import get_dataset_pairs, get_dataset_view, save_generation
from server.services.dedup import compute_hash_from_content

logger = logging.getLogger(__name__)

# Where the pairs land in the repo. Referenced by the dataset card's `configs`
# block, so the Hub viewer picks the file up without further configuration.
DATA_PATH_IN_REPO = "data/train.jsonl"


class HuggingFaceNotConfiguredError(RuntimeError):
    """Raised when an export is attempted without a Hub token."""


class HuggingFaceRepoPublicError(RuntimeError):
    """Raised when the target repo already exists and is public."""


def is_huggingface_configured() -> bool:
    """True when a Hub token is set (the namespace is optional)."""
    return bool(config.hf_token)


def _require_token() -> str:
    if not config.hf_token:
        raise HuggingFaceNotConfiguredError(
            "Hugging Face is not configured. Set HF_TOKEN (a token with write "
            "access) to export datasets to the Hub."
        )
    return config.hf_token


def _api():
    """Build an HfApi client. Imported lazily so the SDK stays optional at boot."""
    from huggingface_hub import HfApi

    return HfApi(token=_require_token())


def slugify(name: str) -> str:
    """Turn a dataset name into a valid Hub repo name.

    The Hub accepts alphanumerics, ``-``, ``_`` and ``.``; anything else is
    collapsed into a single dash.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return slug or "dataset"


def _card_metadata(card_data: Any) -> Dict[str, Any]:
    """Pull the handful of dataset-card fields worth surfacing.

    ``card_data`` is a :class:`huggingface_hub.DatasetCardData` (dict-like via
    ``to_dict()``) or ``None`` when the repo has no card / no YAML front
    matter yet.
    """
    if card_data is None:
        return {"pretty_name": None, "language": None, "license": None, "size_category": None}
    as_dict = card_data.to_dict() if hasattr(card_data, "to_dict") else dict(card_data)
    language = as_dict.get("language")
    size_categories = as_dict.get("size_categories")
    return {
        "pretty_name": as_dict.get("pretty_name"),
        "language": language if isinstance(language, list) else ([language] if language else None),
        "license": as_dict.get("license"),
        "size_category": (
            size_categories[0] if isinstance(size_categories, list) and size_categories else size_categories
        ),
    }


def list_user_datasets() -> Dict[str, Any]:
    """The Hub dataset repos owned by the configured account, newest first.

    Uses the token's own namespace (``HF_NAMESPACE``, or the token's account),
    same as :func:`resolve_repo_id` — so this lists exactly the account an
    export would land in, private repos included. Fetches ``full=True`` so the
    response carries everything the Hub knows about each repo (card metadata,
    tags, storage size, gated status, …), not just the default summary fields.
    """
    _require_token()
    api = _api()
    namespace = config.hf_namespace or api.whoami().get("name")
    if not namespace:
        raise HuggingFaceNotConfiguredError(
            "Could not determine the Hugging Face namespace. Set HF_NAMESPACE "
            "(your user or organization name)."
        )

    datasets = list(
        api.list_datasets(
            author=namespace,
            sort="last_modified",
            full=True,
            token=config.hf_token,
        )
    )
    rows = [
        {
            "id": d.id,
            "url": f"https://huggingface.co/datasets/{d.id}",
            "author": getattr(d, "author", None),
            "private": bool(getattr(d, "private", False)),
            "gated": getattr(d, "gated", None) or False,
            "disabled": bool(getattr(d, "disabled", False)),
            "downloads": getattr(d, "downloads", None),
            "downloads_all_time": getattr(d, "downloads_all_time", None),
            "likes": getattr(d, "likes", None),
            "tags": getattr(d, "tags", None) or [],
            "description": getattr(d, "description", None),
            "file_count": (
                len(d.siblings) if getattr(d, "siblings", None) is not None else None
            ),
            "used_storage": getattr(d, "used_storage", None),
            "sha": getattr(d, "sha", None),
            "created_at": _json_safe(getattr(d, "created_at", None)),
            "last_modified": _json_safe(getattr(d, "last_modified", None)),
            **_card_metadata(getattr(d, "card_data", None)),
        }
        for d in datasets
    ]
    return {"namespace": namespace, "total": len(rows), "datasets": rows}


# Tabular formats the import can read, most specific first. Parquet needs
# pyarrow, which is not a dependency — it is only tried when importable.
_DATA_EXTENSIONS = (".jsonl", ".json", ".csv", ".parquet")

# Column names seen in the wild for each side of a pair, in priority order.
_QUESTION_KEYS = ("question", "query", "prompt", "instruction", "q")
_ANSWER_KEYS = ("answer", "response", "output", "completion", "a")
_CONTEXT_KEYS = ("context", "source_text", "passage")

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _list_repo_files(repo_id: str) -> List[str]:
    """Every file path in the dataset repo. ValueError if the repo is unknown."""
    from huggingface_hub.errors import RepositoryNotFoundError

    try:
        return list(_api().list_repo_files(repo_id, repo_type="dataset"))
    except RepositoryNotFoundError:
        raise ValueError(f"Hugging Face dataset repo '{repo_id}' not found")


def _download_file(repo_id: str, filename: str) -> bytes:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="dataset",
        token=_require_token(),
    )
    with open(path, "rb") as f:
        return f.read()


def _parquet_available() -> bool:
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False
    return True


def _pick_data_files(files: List[str]) -> List[str]:
    """The data files to import: every file of the best readable format.

    All files of that format are kept (train/validation/test splits alike) —
    quality control wants the whole dataset, not one split.
    """
    readable = [
        ext for ext in _DATA_EXTENSIONS if ext != ".parquet" or _parquet_available()
    ]
    for ext in readable:
        picked = sorted(f for f in files if f.lower().endswith(ext))
        if picked:
            return picked
    return []


def _parse_rows(filename: str, raw: bytes) -> List[Dict[str, Any]]:
    """Decode one data file into a list of row dicts."""
    lower = filename.lower()
    if lower.endswith(".parquet"):
        import io

        import pyarrow.parquet as pq

        return pq.read_table(io.BytesIO(raw)).to_pylist()

    text = raw.decode("utf-8-sig")
    if lower.endswith(".csv"):
        import csv
        import io

        return list(csv.DictReader(io.StringIO(text)))

    if lower.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None  # JSON Lines saved with a .json extension — fall through.
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            # {"data": [...]} / {"train": [...]}-style wrappers.
            for value in data.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value
            return [data]

    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _first_text(row: Dict[str, Any], keys) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _from_messages(messages: Any) -> Tuple[str, str]:
    """(question, answer) from a chat transcript: the first user turn and the
    assistant turn that follows it."""
    if not isinstance(messages, list):
        return "", ""
    question = answer = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role") or message.get("from")
        content = message.get("content") or message.get("value") or ""
        if not isinstance(content, str):
            continue
        if not question and role in ("user", "human"):
            question = content.strip()
        elif question and role in ("assistant", "gpt", "bot"):
            answer = content.strip()
            break
    return question, answer


def _row_to_pair(row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Map a row onto question/answer/context, whatever the column naming.

    Handles the app's own export (question/answer/context), instruction
    tuning (instruction + optional input → output), prompt/response pairs and
    chat transcripts (``messages`` / ``conversations``). Returns None when the
    row carries no usable pair.
    """
    question = _first_text(row, _QUESTION_KEYS)
    answer = _first_text(row, _ANSWER_KEYS)
    context = _first_text(row, _CONTEXT_KEYS)

    extra_input = row.get("input")
    if isinstance(extra_input, str) and extra_input.strip():
        if question:
            # Alpaca-style: the input is the material the instruction applies to.
            context = context or extra_input.strip()
        else:
            question = extra_input.strip()

    if not (question and answer):
        q, a = _from_messages(row.get("messages") or row.get("conversations"))
        question, answer = question or q, answer or a

    if not (question and answer):
        return None
    return {"question": question, "answer": answer, "context": context}


def _confidence(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def import_dataset_from_hub(
    repo_id: str, dataset_name: Optional[str] = None
) -> Dict[str, Any]:
    """Pull a Hub dataset repo's Q/A pairs into local storage.

    Finds the repo's data files itself (JSONL, JSON, CSV — Parquet when pyarrow
    is installed) rather than assuming the layout :func:`export_dataset_to_hub`
    writes, maps the usual column namings onto question/answer/context, and
    upserts the pairs into a local dataset by content hash — re-importing is
    idempotent, and the existing analysis pipeline (duplicate detection, score
    stats, quality rules) then runs over it like any other dataset.

    Raises :class:`HuggingFaceNotConfiguredError` without a token, and
    ValueError (naming what was found) when the repo is unknown, has no
    readable data file, or no row maps onto a Q/A pair.
    """
    _require_token()
    local_name = dataset_name or repo_id.split("/")[-1]

    files = _list_repo_files(repo_id)
    data_files = _pick_data_files(files)
    if not data_files:
        hint = ""
        if any(f.lower().endswith(".parquet") for f in files):
            hint = " (its data is Parquet, which needs the pyarrow package)"
        raise ValueError(
            f"'{repo_id}' has no readable data file{hint}. "
            f"Files in the repo: {', '.join(files) or '(none)'}"
        )

    source_fallback = f"huggingface://{repo_id}"
    items: List[Dict[str, Any]] = []
    columns: set[str] = set()
    skipped = 0
    for filename in data_files:
        rows = _parse_rows(filename, _download_file(repo_id, filename))
        logger.info(
            "HF import %s: %s → %d row(s)", repo_id, filename, len(rows)
        )
        for row in rows:
            columns.update(row.keys())
            pair = _row_to_pair(row)
            if pair is None:
                skipped += 1
                continue
            source_url = row.get("source_url") or source_fallback
            row_id = row.get("id")
            # Keep the id only when it is one of our own content hashes (an
            # app export); a foreign dataset's "0", "1"… would collide across
            # datasets, since pair ids are global primary keys.
            if not (isinstance(row_id, str) and _SHA256_HEX.match(row_id)):
                row_id = compute_hash_from_content(
                    pair["question"], pair["answer"], pair["context"], source_url
                )
            items.append(
                {
                    "id": row_id,
                    **pair,
                    "source_url": source_url,
                    "confidence": _confidence(
                        row.get("confidence", row.get("score"))
                    ),
                    "metadata": {"imported_from": repo_id, "file": filename},
                }
            )

    if not items:
        raise ValueError(
            f"'{repo_id}' has no row that maps onto a question/answer pair "
            f"(read {', '.join(data_files)}; columns found: "
            f"{', '.join(sorted(columns)) or '(none)'})"
        )

    # Two rows with the same content hash would collide on the primary key.
    unique = list({item["id"]: item for item in items}.values())
    logger.info(
        "HF import %s → dataset %r: %d pair(s), %d duplicate(s) merged, "
        "%d row(s) skipped (no question/answer)",
        repo_id,
        local_name,
        len(unique),
        len(items) - len(unique),
        skipped,
    )

    result = save_generation(
        local_name,
        unique,
        source_url=source_fallback,
        stats={"total": len(unique)},
    )
    return {
        "dataset_name": local_name,
        "repo_id": repo_id,
        "pairs_imported": result["created_count"],
        "version": result["version"],
    }


def resolve_repo_id(dataset_name: str, repo_id: Optional[str] = None) -> str:
    """The full ``namespace/name`` the export writes to.

    An explicit ``repo_id`` wins. Otherwise the name is derived from the
    dataset and the namespace from ``HF_NAMESPACE`` — falling back to the
    token's own account, so a working token is enough to export.
    """
    if repo_id:
        return repo_id
    namespace = config.hf_namespace or _api().whoami().get("name")
    if not namespace:
        raise HuggingFaceNotConfiguredError(
            "Could not determine the Hugging Face namespace. Set HF_NAMESPACE "
            "(your user or organization name)."
        )
    return f"{namespace}/{slugify(dataset_name)}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _to_jsonl(pairs: List[Dict[str, Any]]) -> bytes:
    """One JSON object per line — the shape training tooling expects."""
    lines = []
    for pair in pairs:
        lines.append(
            json.dumps(
                {
                    "id": pair.get("id"),
                    "question": pair.get("question", ""),
                    "answer": pair.get("answer", ""),
                    "context": pair.get("context", ""),
                    "source_url": pair.get("source_url") or None,
                    "confidence": pair.get("confidence"),
                    "created_at": _json_safe(pair.get("created_at")),
                },
                ensure_ascii=False,
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _size_category(count: int) -> str:
    if count < 1_000:
        return "n<1K"
    if count < 10_000:
        return "1K<n<10K"
    if count < 100_000:
        return "10K<n<100K"
    return "100K<n<1M"


def _dataset_card(
    dataset_name: str,
    pair_count: int,
    target_language: Optional[str],
    source_labels: List[str],
) -> bytes:
    """A dataset card whose front matter wires up the Hub viewer."""
    language = target_language or "en"
    sources = "\n".join(f"- `{label}`" for label in source_labels[:20])
    if len(source_labels) > 20:
        sources += f"\n- …and {len(source_labels) - 20} more"

    card = f"""---
language:
- {language}
size_categories:
- {_size_category(pair_count)}
task_categories:
- question-answering
tags:
- synthetic
- question-answering
configs:
- config_name: default
  data_files: {DATA_PATH_IN_REPO}
---

# {dataset_name}

{pair_count} question/answer pairs generated with
[dataset-generator](https://github.com/KevinDeBenedetti/dataset-generator).

This dataset is **private**.

## Fields

| Field | Description |
| --- | --- |
| `id` | Content hash of the pair (stable across regenerations) |
| `question` | The generated question |
| `answer` | The generated answer |
| `context` | The cleaned source text the pair was derived from |
| `source_url` | Where the content came from (page URL, `file://`, `github://`) |
| `confidence` | Model-reported confidence, when scored |
| `created_at` | When the pair was generated |

## Sources

{sources or "_No source recorded._"}
"""
    return card.encode("utf-8")


def export_dataset_to_hub(
    dataset_name: str, repo_id: Optional[str] = None
) -> Dict[str, Any]:
    """Push a dataset to the Hub as a private dataset repo.

    Raises :class:`HuggingFaceNotConfiguredError` without a token, ValueError
    for an unknown/empty dataset, and :class:`HuggingFaceRepoPublicError` when
    the target repo already exists and is public.
    """
    _require_token()

    dataset = get_dataset_view(dataset_name)
    if dataset is None:
        raise ValueError(f"Dataset '{dataset_name}' not found")
    pairs = get_dataset_pairs(dataset_name)
    if not pairs:
        raise ValueError(f"Dataset '{dataset_name}' has no Q/A pairs to export")

    api = _api()
    target = resolve_repo_id(dataset_name, repo_id)

    # Create it private, or confirm an existing one already is. `private=True`
    # is ignored when the repo exists, so this check is the only thing standing
    # between a re-export and a public upload.
    from huggingface_hub.errors import RepositoryNotFoundError

    api.create_repo(target, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(target, repo_type="dataset")
    except RepositoryNotFoundError:  # pragma: no cover — just created above
        info = None
    if info is not None and getattr(info, "private", None) is False:
        raise HuggingFaceRepoPublicError(
            f"The Hugging Face repo '{target}' already exists and is public. "
            "Exporting would publish this dataset — make the repo private on "
            "the Hub, or export to a different repo id."
        )

    source_labels = sorted({str(p["source_url"]) for p in pairs if p.get("source_url")})
    api.upload_file(
        path_or_fileobj=_to_jsonl(pairs),
        path_in_repo=DATA_PATH_IN_REPO,
        repo_id=target,
        repo_type="dataset",
        commit_message=f"Export {len(pairs)} Q/A pair(s) from {dataset_name}",
    )
    api.upload_file(
        path_or_fileobj=_dataset_card(
            dataset_name,
            len(pairs),
            dataset.get("target_language"),
            list(source_labels),
        ),
        path_in_repo="README.md",
        repo_id=target,
        repo_type="dataset",
        commit_message=f"Update the dataset card for {dataset_name}",
    )

    logger.info(
        "Exported dataset '%s' to https://huggingface.co/datasets/%s",
        dataset_name,
        target,
    )
    return {
        "dataset_name": dataset_name,
        "repo_id": target,
        "url": f"https://huggingface.co/datasets/{target}",
        "private": True,
        "pairs_exported": len(pairs),
    }
