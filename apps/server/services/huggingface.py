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
from typing import Any, Dict, List, Optional

from server.core.config import config
from server.services.datasets import get_dataset_pairs, get_dataset_view

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
