import logging
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from langfuse import get_client, Langfuse


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

    # Create the dataset items
    created_items = []
    failed_items = []

    for item in dataset_items:
        try:
            created_item = langfuse_client.create_dataset_item(
                dataset_name=dataset_config["name"],
                input=item["input"],
                expected_output=item["expected_output"],
                metadata=item["metadata"],
                id=item["id"],
            )
            created_items.append(
                created_item.id if hasattr(created_item, "id") else item["id"]
            )
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


def sync_qa_to_langfuse(
    dataset_name: str,
    items: List[Dict[str, Any]],
    *,
    source_url: str,
    stats: Optional[Dict[str, Any]] = None,
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

    logging.info(f"Syncing dataset '{dataset_name}' as version {version} to Langfuse")
    langfuse_client.create_dataset(
        name=dataset_name,
        description=f"Auto-generated QA dataset from {source_url}",
        metadata=dataset_metadata,
    )

    created, failed = [], []
    for item in items:
        try:
            item_metadata = {**(item.get("metadata") or {}), "version": version}
            langfuse_client.create_dataset_item(
                dataset_name=dataset_name,
                input=item["input"],
                expected_output=item.get("expected_output"),
                metadata=item_metadata,
                id=item.get("id"),
            )
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
    try:
        dataset = langfuse_client.get_dataset(dataset_name)

        def _snapshot_task(*, item, **_):
            # Identity task: we only want the run recorded against each item,
            # not an evaluation. The expected output is the snapshotted value.
            return item.expected_output

        dataset.run_experiment(
            name=run_name,
            run_name=run_name,
            description=f"Generation {run_name} from {source_url}",
            task=_snapshot_task,
            metadata=run_metadata,
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
    required = ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_HOST"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logging.info(f"Langfuse not configured, missing env vars: {missing}")
        return False
    return True


def is_langfuse_available() -> bool:
    """
    Initializes the Langfuse client and validates the credentials against the
    server. Returns True only if the keys authenticate, False otherwise.

    ``get_client()`` is lazy in the v4 SDK — it never raises on invalid or
    unreachable credentials — so we call ``auth_check()`` to make a real
    request. This is what distinguishes "env vars are set" (``is_langfuse_configured``)
    from "the secrets actually work".
    """
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
