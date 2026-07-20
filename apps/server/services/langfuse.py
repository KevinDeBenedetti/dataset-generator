import logging
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx
from langfuse import get_client, Langfuse


class LangfuseUnavailableError(RuntimeError):
    """Raised when a dataset read is attempted but Langfuse isn't reachable."""


def _normalize_langfuse_host() -> None:
    """Accept ``LANGFUSE_BASE_URL`` as an alias for ``LANGFUSE_HOST``.

    The Langfuse SDK (and ``is_langfuse_configured``) reads ``LANGFUSE_HOST``,
    but ``LANGFUSE_BASE_URL`` is a common spelling. If only the alias is set,
    mirror it into ``LANGFUSE_HOST`` so both the SDK and our config checks work.
    """
    if not os.getenv("LANGFUSE_HOST") and os.getenv("LANGFUSE_BASE_URL"):
        os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]


# Run at import so the SDK's lazy ``get_client()`` picks up the host from either var.
_normalize_langfuse_host()


def prepare_langfuse_dataset(
    data: List[Dict], dataset_name: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Transforms JSON data into Langfuse Dataset format
    """
    # Create the dataset structure
    dataset = {
        "name": dataset_name,
        "description": f"Automatically generated Q&A Dataset - {dataset_name}",
        "metadata": {
            "source": "internal_qa_generator",
            "total_items": len(data),
            "created_from": dataset_name,
        },
    }

    # Create the dataset items
    items = []
    for idx, item in enumerate(data):
        langfuse_item = {
            "id": item.get("id", f"item_{idx}"),
            "input": {"question": item["question"]},
            "expected_output": {"answer": item["answer"]},
            "metadata": {
                "confidence": item.get("confidence", 1.0),
                "context": item.get("context", ""),
                "original_id": item.get("id", f"item_{idx}"),
            },
        }
        items.append(langfuse_item)

    return dataset, items


def load_json_dataset(file_path: Path) -> List[Dict]:
    """
    Loads a JSON dataset file
    """
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        with file_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON file: {e}")
    except Exception as e:
        raise ValueError(f"Error reading the file: {e}")


def scan_dataset_files(qa_dir: Path) -> List[str]:
    """
    Scans the directory to find available JSON files
    """
    if qa_dir.exists() and qa_dir.is_dir():
        return sorted([p.name for p in qa_dir.glob("*.json") if p.is_file()])
    return []


def create_langfuse_dataset_with_items(
    dataset_config: Dict[str, Any],
    dataset_items: List[Dict[str, Any]],
    langfuse_client: Optional[Langfuse] = None,
) -> Dict[str, Any]:
    """
    Creates a dataset in Langfuse with its items
    """
    if langfuse_client is None:
        langfuse_client = get_client()

    logging.info(f"Creating dataset: {dataset_config['name']}")

    # Create the dataset in Langfuse
    dataset = langfuse_client.create_dataset(
        name=dataset_config["name"],
        description=dataset_config.get("description", "Automatically created dataset"),
        metadata=dataset_config.get("metadata", {}),
    )

    # Create the dataset items via the REST API directly, not the SDK client:
    # see the comment in sync_qa_to_langfuse for why (media_references).
    host, public_key, secret_key = _langfuse_credentials()
    created_items = []
    failed_items = []

    for item in dataset_items:
        try:
            resp = httpx.post(
                f"{host}/api/public/dataset-items",
                json={
                    "datasetName": dataset_config["name"],
                    "input": item["input"],
                    "expectedOutput": item["expected_output"],
                    "metadata": item["metadata"],
                    "id": item["id"],
                },
                auth=(public_key, secret_key),
                timeout=30.0,
            )
            resp.raise_for_status()
            created_items.append(item["id"])
            logging.info(f"Item created: {item['id']}")
        except Exception as e:
            logging.error(f"Error creating item {item['id']}: {e}")
            failed_items.append({"id": item["id"], "error": str(e)})
            continue

    return {
        "dataset_id": dataset.id if hasattr(dataset, "id") else dataset_config["name"],
        "dataset_name": dataset_config["name"],
        "total_items": len(dataset_items),
        "created_items": created_items,
        "created_count": len(created_items),
        "failed_items": failed_items,
        "failed_count": len(failed_items),
    }


def get_next_dataset_version(
    dataset_name: str, langfuse_client: Optional[Langfuse] = None
) -> int:
    """Return the next version number for a dataset (DVC-like, 1-based).

    Each generation records a dataset *run* in Langfuse, so the count of
    existing runs is the version history. The next version is therefore
    ``len(existing_runs) + 1``. Falls back to ``1`` when the dataset/runs can't
    be read (e.g. the dataset doesn't exist yet).
    """
    if langfuse_client is None:
        langfuse_client = get_client()
    try:
        runs = langfuse_client.get_dataset_runs(dataset_name=dataset_name)
        data = getattr(runs, "data", None) or []
        return len(data) + 1
    except Exception as e:  # noqa: BLE001 — first version of a new dataset
        logging.info(f"No existing runs for '{dataset_name}' ({e}); starting at v1")
        return 1


def _summarize_run(run: Any) -> Dict[str, Any]:
    """Map a Langfuse dataset run to a compact, UI-friendly summary."""
    metadata = getattr(run, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    created_at = getattr(run, "created_at", None)
    return {
        "run_name": getattr(run, "name", None),
        "version": metadata.get("version"),
        "description": getattr(run, "description", None),
        "item_count": metadata.get("item_count"),
        "source_url": metadata.get("source_url"),
        "created_at": (
            created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
        ),
        "metadata": metadata,
    }


def list_dataset_runs(
    dataset_name: str, langfuse_client: Optional[Langfuse] = None
) -> List[Dict[str, Any]]:
    """Return the version/run history of a dataset from Langfuse, newest first.

    Each generation records a dataset run named ``v{n}`` (see
    :func:`sync_qa_to_langfuse`); reading them back gives the DVC-like history
    for the UI. Returns an empty list when the dataset has no runs.
    """
    if langfuse_client is None:
        langfuse_client = get_client()

    try:
        runs = langfuse_client.get_dataset_runs(dataset_name=dataset_name)
    except httpx.HTTPError as e:
        logging.warning(f"Langfuse unreachable while listing runs for '{dataset_name}': {e}")
        raise LangfuseUnavailableError(f"Could not reach Langfuse: {e}") from e
    data = getattr(runs, "data", None) or []

    summaries = [_summarize_run(run) for run in data]
    # Newest first: prefer the explicit version, fall back to created_at.
    summaries.sort(
        key=lambda r: (
            r["version"] if r["version"] is not None else -1,
            r["created_at"] or "",
        ),
        reverse=True,
    )
    return summaries


def _summarize_dataset(dataset: Any) -> Dict[str, Any]:
    """Map a Langfuse dataset to a compact, UI-friendly summary."""
    metadata = getattr(dataset, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    created_at = getattr(dataset, "created_at", None)
    updated_at = getattr(dataset, "updated_at", None)
    return {
        "id": getattr(dataset, "id", None),
        "name": getattr(dataset, "name", None),
        "description": getattr(dataset, "description", None),
        # Best-effort: filled by sync_qa_to_langfuse's dataset metadata.
        "item_count": metadata.get("total_items"),
        "version": metadata.get("version"),
        "source_url": metadata.get("source_url"),
        "created_at": (
            created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
        ),
        "updated_at": (
            updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at
        ),
        "metadata": metadata,
    }


def list_datasets(langfuse_client: Optional[Langfuse] = None) -> List[Dict[str, Any]]:
    """Return every dataset present in Langfuse, newest first.

    Walks the paginated ``/datasets`` API so all datasets are returned, not just
    the first page. Returns an empty list when the project has no datasets.
    """
    if langfuse_client is None:
        langfuse_client = get_client()

    summaries: List[Dict[str, Any]] = []
    page = 1
    try:
        while True:
            resp = langfuse_client.api.datasets.list(page=page, limit=100)
            data = getattr(resp, "data", None) or []
            summaries.extend(_summarize_dataset(d) for d in data)

            meta = getattr(resp, "meta", None)
            total_pages = getattr(meta, "total_pages", None) if meta else None
            if not data or not total_pages or page >= total_pages:
                break
            page += 1
    except httpx.HTTPError as e:
        logging.warning(f"Langfuse unreachable while listing datasets: {e}")
        raise LangfuseUnavailableError(f"Could not reach Langfuse: {e}") from e

    # Newest first by creation date (falls back to name for stability).
    summaries.sort(key=lambda d: (d["created_at"] or "", d["name"] or ""), reverse=True)
    return summaries


def _langfuse_credentials() -> Tuple[str, str, str]:
    """Return ``(host, public_key, secret_key)`` or raise if not configured."""
    _normalize_langfuse_host()
    host = os.getenv("LANGFUSE_HOST")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not (host and public_key and secret_key):
        raise RuntimeError("Langfuse is not configured (LANGFUSE_* env vars missing)")
    return host.rstrip("/"), public_key, secret_key


def _summarize_rest_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map a raw REST dataset item (camelCase) to our compact snake_case dict."""
    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "input": item.get("input"),
        "expected_output": item.get("expectedOutput"),
        "metadata": metadata,
        "source_trace_id": item.get("sourceTraceId"),
        "dataset_id": item.get("datasetId"),
        "dataset_name": item.get("datasetName"),
        "created_at": item.get("createdAt"),
    }


def get_dataset_items(dataset_name: str) -> List[Dict[str, Any]]:
    """Return every item of a Langfuse dataset (the Q/A pairs).

    Reads the paginated public REST API directly (``GET /api/public/dataset-items``)
    rather than the typed SDK client: the SDK's ``DatasetItem`` model requires a
    ``media_references`` field that older Langfuse servers don't return, which
    makes the SDK call fail validation. Filtered by ``datasetName`` (the API's
    ``datasetId`` filter is silently ignored). Each item keeps its ``status`` so
    callers can drop archived items. Empty list when the dataset has no items.
    """
    host, public_key, secret_key = _langfuse_credentials()

    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        resp = httpx.get(
            f"{host}/api/public/dataset-items",
            params={"datasetName": dataset_name, "page": page, "limit": 100},
            auth=(public_key, secret_key),
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or []
        items.extend(_summarize_rest_item(d) for d in data)

        meta = body.get("meta") or {}
        total_pages = meta.get("totalPages")
        if not data or not total_pages or page >= total_pages:
            break
        page += 1

    return items


def count_dataset_items(dataset_name: str) -> int:
    """Total number of items in a dataset, via the REST pagination meta.

    A single ``limit=1`` request (cheap) reads ``meta.totalItems`` rather than
    fetching every item just to count them — used by the dataset-list overview
    where the per-dataset count would otherwise be missing/stale. Counts every
    item Langfuse reports (the rare archived ones included).
    """
    host, public_key, secret_key = _langfuse_credentials()
    resp = httpx.get(
        f"{host}/api/public/dataset-items",
        params={"datasetName": dataset_name, "page": 1, "limit": 1},
        auth=(public_key, secret_key),
        timeout=30.0,
    )
    resp.raise_for_status()
    meta = resp.json().get("meta") or {}
    total = meta.get("totalItems")
    return total if isinstance(total, int) else 0


def delete_dataset_item(item_id: str) -> None:
    """Delete a single dataset item (and its run items) from Langfuse.

    Irreversible (``DELETE /api/public/dataset-items/{id}``). Uses the REST API
    directly for the same reason as :func:`get_dataset_items`.
    """
    host, public_key, secret_key = _langfuse_credentials()
    resp = httpx.delete(
        f"{host}/api/public/dataset-items/{item_id}",
        auth=(public_key, secret_key),
        timeout=30.0,
    )
    resp.raise_for_status()


def sync_qa_to_langfuse(
    dataset_name: str,
    items: List[Dict[str, Any]],
    *,
    source_url: str,
    stats: Optional[Dict[str, Any]] = None,
    target_language: Optional[str] = None,
    version: Optional[int] = None,
    langfuse_client: Optional[Langfuse] = None,
) -> Dict[str, Any]:
    """Create/update a Langfuse dataset and record a versioned run.

    This is the DVC-like step run at generation time:

    1. Upserts the dataset, stamping ``metadata.version`` and source info.
    2. Upserts each QA item. Item ids are content hashes, so re-runs are
       idempotent — unchanged pairs don't duplicate, new pairs are added.
    3. Records a dataset *run* named ``v{version}`` (the immutable "commit"),
       linking the current items to that version with run metadata.

    Returns a summary describing the synced version.
    """
    if langfuse_client is None:
        langfuse_client = get_client()

    stats = stats or {}
    if version is None:
        version = get_next_dataset_version(dataset_name, langfuse_client)

    run_name = f"v{version}"
    dataset_metadata = {
        "source": "dataset-generator",
        "source_url": source_url,
        "version": version,
        "latest_run": run_name,
        "total_items": len(items),
        **stats,
    }
    # Surface the dataset's language so the list/dashboard view can show it
    # (read back via metadata.target_language). Only set when known, to avoid
    # clobbering an existing value with None on a re-sync.
    if target_language:
        dataset_metadata["target_language"] = target_language

    logging.info(f"Syncing dataset '{dataset_name}' as version {version} to Langfuse")
    langfuse_client.create_dataset(
        name=dataset_name,
        description=f"Auto-generated QA dataset from {source_url}",
        metadata=dataset_metadata,
    )

    # Item creation goes through the REST API directly rather than the SDK's
    # create_dataset_item, for the same reason as get_dataset_items: the SDK
    # parses the response into a DatasetItem model that requires a
    # media_references field older/some Langfuse servers don't return, which
    # fails client-side response validation even though the item was created
    # successfully server-side (the POST already went through by then).
    host, public_key, secret_key = _langfuse_credentials()
    created, failed = [], []
    for item in items:
        try:
            item_metadata = {**(item.get("metadata") or {}), "version": version}
            resp = httpx.post(
                f"{host}/api/public/dataset-items",
                json={
                    "datasetName": dataset_name,
                    "input": item["input"],
                    "expectedOutput": item.get("expected_output"),
                    "metadata": item_metadata,
                    "id": item.get("id"),
                },
                auth=(public_key, secret_key),
                timeout=30.0,
            )
            resp.raise_for_status()
            created.append(item.get("id"))
        except Exception as e:  # noqa: BLE001 — keep going on a single bad item
            logging.error(f"Error syncing item {item.get('id')}: {e}")
            failed.append({"id": item.get("id"), "error": str(e)})

    # Record the version as a dataset run (the immutable snapshot/"commit").
    run_metadata = {
        "version": version,
        "source_url": source_url,
        "item_count": len(items),
        **stats,
    }
    # Link each item to the run via the dataset-run-items API. That API requires
    # a trace (or observation) to link to — otherwise it rejects the call with
    # "observationId or traceId must be provided". We create a single lightweight
    # trace for the whole run and attach every item to it: one trace per sync,
    # not one per item. This still avoids run_experiment, which would create a
    # trace AND execute a task for *every* item (costly on large datasets) — we
    # only need the run recorded against the existing items, not an evaluation.
    try:
        run_span = langfuse_client.start_observation(
            name=f"dataset-sync-{run_name}",
            input={"source_url": source_url, "version": version},
            metadata=run_metadata,
        )
        run_trace_id = run_span.trace_id
        run_span.end()

        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            langfuse_client.api.dataset_run_items.create(
                run_name=run_name,
                run_description=f"Generation {run_name} from {source_url}",
                metadata=run_metadata,
                dataset_item_id=item_id,
                trace_id=run_trace_id,
            )
    except Exception as e:  # noqa: BLE001 — items are synced even if the run fails
        logging.warning(f"Could not record dataset run {run_name}: {e}")

    langfuse_client.flush()

    return {
        "dataset_name": dataset_name,
        "version": version,
        "run_name": run_name,
        "total_items": len(items),
        "created_count": len(created),
        "failed_count": len(failed),
        "failed_items": failed,
    }


def normalize_dataset_name(filename: str) -> str:
    """
    Normalizes a filename to create a valid dataset name
    """
    return Path(filename).stem.replace("_", "-").replace(" ", "-")


def is_langfuse_configured() -> bool:
    """
    Checks for the presence of the environment variables required for Langfuse.
    """
    _normalize_langfuse_host()
    required = ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_HOST"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logging.info(f"Langfuse not configured, missing env vars: {missing}")
        return False
    return True


# Memoised result of the (network) auth_check, so we hit Langfuse once per
# process instead of on every generation.
_availability_cache: Optional[bool] = None


def reset_langfuse_availability_cache() -> None:
    """Clear the cached availability (for tests, or after a config change)."""
    global _availability_cache
    _availability_cache = None


def _compute_langfuse_available() -> bool:
    if not is_langfuse_configured():
        return False
    try:
        client = get_client()
        if not client.auth_check():
            logging.warning("Langfuse credentials rejected (auth_check failed)")
            return False
        logging.info("Langfuse client reachable")
        return True
    except Exception as e:
        logging.warning(f"Langfuse client initialization failed: {e}")
        return False


def is_langfuse_available(use_cache: bool = True) -> bool:
    """
    Initializes the Langfuse client and validates the credentials against the
    server. Returns True only if the keys authenticate, False otherwise.

    ``get_client()`` is lazy in the v4 SDK — it never raises on invalid or
    unreachable credentials — so we call ``auth_check()`` to make a real
    request. This is what distinguishes "env vars are set" (``is_langfuse_configured``)
    from "the secrets actually work".

    The result is **memoised**: the auth_check runs once per process, so an
    invalid key is detected once at startup instead of logging a warning on
    every generation. Trade-off: if Langfuse is unreachable on the first check,
    sync stays disabled until the process restarts. Pass ``use_cache=False`` to
    force a fresh check (e.g. after credentials change).
    """
    global _availability_cache
    if use_cache and _availability_cache is not None:
        return _availability_cache

    result = _compute_langfuse_available()
    _availability_cache = result
    return result
