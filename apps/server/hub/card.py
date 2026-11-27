"""The app card of a tabular dataset (``README.md``).

YAML front matter the Hub reads (licence, tags with ``dataset-generator`` so
the card is recognised as the app's, the ``configs`` pointing its viewer at
``data/*.parquet``, the features from the schema), then the description, the
source and its attribution, the schema, the recipe's steps in plain words and
how to load the dataset.
"""

from typing import Any, Dict, List, Optional

import yaml

from server.hub.licences import Licence, resolve
from server.services.hub_repo import APP_CARD_TAG

# DuckDB types → the Hub's `dataset_info.features` dtypes.
_DTYPES = {
    "BIGINT": "int64",
    "INTEGER": "int32",
    "SMALLINT": "int16",
    "TINYINT": "int8",
    "UBIGINT": "uint64",
    "DOUBLE": "float64",
    "FLOAT": "float32",
    "BOOLEAN": "bool",
    "DATE": "date32",
    "TIMESTAMP": "timestamp[us]",
    "VARCHAR": "string",
}


def _dtype(kind: str) -> str:
    base = kind.upper().split("(")[0].strip()
    if base == "DECIMAL":
        return "float64"
    return _DTYPES.get(base, "string")


def describe_step(step: Dict[str, Any]) -> str:
    """One recipe step in plain words."""
    op = step.get("op")
    if op == "select":
        return "Keep the columns " + ", ".join(
            f"`{c}`" for c in step.get("columns", [])
        )
    if op == "rename":
        pairs = ", ".join(
            f"`{a}` → `{b}`" for a, b in (step.get("mapping") or {}).items()
        )
        return f"Rename {pairs}"
    if op == "cast":
        extra = f" (format `{step['format']}`)" if step.get("format") else ""
        return f"Read `{step.get('column')}` as {step.get('to')}{extra}"
    if op == "filter":
        value = step.get("value")
        shown = "" if step.get("operator") in ("is_null", "not_null") else f" {value!r}"
        return (
            f"Keep the rows where `{step.get('column')}` {step.get('operator')}{shown}"
        )
    if op == "dedup":
        cols = step.get("columns") or []
        on = ", ".join(f"`{c}`" for c in cols) if cols else "every column"
        return f"Remove duplicates on {on}, keeping the {step.get('keep', 'first')}"
    if op == "mask":
        return f"Mask `{step.get('column')}` ({step.get('method')})"
    if op == "trim":
        cols = step.get("columns") or []
        return "Trim the spaces of " + (
            ", ".join(f"`{c}`" for c in cols) if cols else "every text column"
        )
    if op == "limit":
        return f"Keep the first {step.get('rows')} rows"
    return str(op)


def attribution(provenance: Dict[str, Any], title: str, licence: Licence) -> str:
    """The "Source: …" sentence (asked for by the Licence Ouverte / Etalab 2.0)."""
    producer = provenance.get("producer") or "the data source's producer"
    updated = provenance.get("last_modified") or provenance.get("fetched_at") or ""
    date = str(updated)[:10]
    return (
        f"Source: {producer} — {title} — {date}"
        if licence.etalab
        else (f"Data from {producer} ({title}), retrieved {date}.")
    )


def tabular_card(
    repo_id: str,
    draft: Dict[str, Any],
    *,
    title: Optional[str] = None,
    language: Optional[List[str]] = None,
) -> str:
    provenance = draft.get("provenance") or {}
    licence = resolve(provenance.get("licence"))
    name = title or repo_id.split("/")[-1]
    schema = draft.get("schema") or []
    front = {
        "license": licence.hf,
        "language": language or ["fr"],
        "pretty_name": name,
        "tags": [
            APP_CARD_TAG,
            "open-data",
            "corpus" if draft.get("kind") == "corpus" else "tabular",
        ],
        "configs": [
            {
                "config_name": "default",
                "data_files": [{"split": "train", "path": "data/*.parquet"}],
            }
        ],
        "dataset_info": {
            "features": [
                {"name": c["name"], "dtype": _dtype(c["type"])} for c in schema
            ],
            "splits": [{"name": "train", "num_examples": int(draft.get("rows") or 0)}],
        },
    }
    lines = [
        "---",
        yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(),
        "---",
        "",
        f"# {name}",
        "",
        f"{draft.get('rows', 0)} rows, {len(schema)} columns, published by "
        "[dataset-generator](https://github.com/KevinDeBenedetti/dataset-generator) "
        "after a human review.",
        "",
        "## Source and attribution",
        "",
        attribution(provenance, provenance.get("title") or name, licence),
        "",
    ]
    if provenance.get("url"):
        lines.append(f"- Original data: <{provenance['url']}>")
    if provenance.get("resource_id"):
        lines.append(f"- Resource: `{provenance['resource_id']}`")
    lines.append(f"- Retrieved: {str(provenance.get('fetched_at') or '')[:19]}")
    licence_text = licence.name
    if licence.url:
        licence_text = f"[{licence.name}]({licence.url})"
    elif provenance.get("licence"):
        licence_text = f"{provenance['licence']} ({licence.name})"
    lines += [f"- Licence: {licence_text}", "", "## Schema", ""]
    lines += ["| Column | Type |", "| --- | --- |"]
    lines += [f"| `{c['name']}` | {c['type']} |" for c in schema]
    steps = draft.get("steps") or []
    lines += ["", "## How it was made", ""]
    if steps:
        lines += [f"{i}. {describe_step(s)}" for i, s in enumerate(steps, 1)]
    else:
        lines.append("The data source's rows, as they are.")
    lines += [
        "",
        "## How to load it",
        "",
        "```python",
        "from datasets import load_dataset",
        "",
        f'ds = load_dataset("{repo_id}")',
        "```",
        "",
        "```python",
        "import pandas as pd",
        "",
        f'df = pd.read_parquet("hf://datasets/{repo_id}/data/")',
        "```",
        "",
    ]
    return "\n".join(lines)
