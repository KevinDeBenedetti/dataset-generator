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
        description=dataset_config.get("description", "Dataset créé automatiquement"),
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
    Attempts to initialize the Langfuse client to verify connectivity.
    Returns True if the client initializes correctly, False otherwise.
    """
    if not is_langfuse_configured():
        return False
    try:
        _ = get_client()
        logging.info("Langfuse client reachable")
        return True
    except Exception as e:
        logging.warning(f"Langfuse client initialization failed: {e}")
        return False
