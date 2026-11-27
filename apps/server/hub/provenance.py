"""``manifest.json`` of a tabular dataset: where the rows came from, what made
them, and the checksum of each Parquet file."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def manifest(
    draft: Dict[str, Any], run_id: str, files: Dict[str, Path]
) -> Dict[str, Any]:
    from server.main import APP_VERSION

    return {
        "kind": "table",
        "app": {"name": "dataset-generator", "version": APP_VERSION},
        "run_id": run_id,
        "rows": draft.get("rows"),
        "provenance": draft.get("provenance") or {},
        "fingerprint": draft.get("fingerprint"),
        "previous_fingerprint": draft.get("previous_fingerprint"),
        "recipe": {
            "id": draft.get("recipe_id"),
            "output_kind": "table",
            "steps": draft.get("steps") or [],
        },
        "schema": draft.get("schema") or [],
        "files": [
            {"path": path, "sha256": sha256_file(local), "bytes": local.stat().st_size}
            for path, local in sorted(files.items())
        ],
    }


def manifest_bytes(data: Dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n").encode()


def data_paths(count: int) -> List[str]:
    """The Parquet shards' names, as the Hub's viewer reads them."""
    return [f"data/train-{i:05d}-of-{count:05d}.parquet" for i in range(count)]
