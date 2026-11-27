"""What a file is: its format, and for text its encoding and delimiter.

The extension says what the file claims to be; the first bytes say what it
is. A file whose content contradicts its extension (a CSV named ``.json``) is
refused rather than guessed.
"""

import codecs
import csv
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from server.connectors.base import FORMATS, ConnectorError

_SAMPLE = 64 * 1024
_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    ".txt": "csv",
    ".json": "json",
    ".geojson": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".xlsx": "xlsx",
}
_DELIMITERS = ";,\t|"


@dataclass
class Sniffed:
    format: str
    options: Dict[str, Any] = field(default_factory=dict)


def format_from_name(filename: str) -> Optional[str]:
    return _EXTENSIONS.get(Path(filename).suffix.lower())


def _encoding(sample: bytes) -> str:
    """utf-8 (``utf-8-sig`` with a BOM), else Windows-1252, else Latin-1: the
    encodings of data.gouv.fr's files."""
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        # A sample may end in the middle of a multi-byte character.
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        sample.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        return "latin-1"


def _delimiter(text: str, hint: Optional[str]) -> str:
    lines = [line for line in text.splitlines()[:50] if line.strip()]
    if not lines:
        return hint or ","
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=_DELIMITERS)
        return dialect.delimiter
    except csv.Error:
        pass
    # The delimiter that splits the header into the most columns, consistently.
    counts = {d: lines[0].count(d) for d in _DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else (hint or ",")


def _looks_like_json(text: str) -> Optional[str]:
    stripped = text.lstrip()
    if not stripped:
        return None
    if stripped[0] == "[":
        return "json"
    if stripped[0] != "{":
        return None
    first = stripped.splitlines()[0].strip()
    try:
        json.loads(first)
        rest = [line for line in stripped.splitlines()[1:3] if line.strip()]
        if rest and all(line.strip().startswith("{") for line in rest):
            return "jsonl"
    except json.JSONDecodeError:
        pass
    return "json"


def _is_xlsx(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(name.startswith("xl/") for name in archive.namelist())
    except zipfile.BadZipFile:
        return False


def sniff(
    path: Path, filename: str, overrides: Optional[Dict[str, Any]] = None
) -> Sniffed:
    """The format and reading options of ``path`` (named ``filename`` by the
    user); ``overrides`` (format, delimiter, encoding, sheet, json_path) win."""
    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    claimed = overrides.get("format") or format_from_name(filename)
    with path.open("rb") as stream:
        head = stream.read(_SAMPLE)
    if not head:
        raise ConnectorError("The file is empty")

    if head.startswith(b"PAR1"):
        actual = "parquet"
    elif head.startswith(b"PK\x03\x04"):
        if not _is_xlsx(path):
            raise ConnectorError("This ZIP file is not an Excel workbook (.xlsx)")
        actual = "xlsx"
    elif head.startswith((b"\xd0\xcf\x11\xe0", b"\x09\x08")):
        raise ConnectorError("Old Excel files (.xls) are not read: save it as .xlsx")
    else:
        actual = None

    if actual is not None:
        if claimed and claimed != actual:
            raise ConnectorError(
                f"This file is {actual.upper()}, not {claimed.upper()}: check its name or format"
            )
        options: Dict[str, Any] = {}
        if actual == "xlsx" and overrides.get("sheet"):
            options["sheet"] = str(overrides["sheet"])
        return Sniffed(actual, options)

    encoding = overrides.get("encoding") or _encoding(head)
    try:
        text = head.decode(encoding, errors="ignore")
    except LookupError:
        raise ConnectorError(f"Unknown encoding '{encoding}'") from None
    json_kind = _looks_like_json(text)
    if claimed in ("parquet", "xlsx"):
        raise ConnectorError(
            f"This file is text, not {claimed.upper()}: check its name or format"
        )
    if claimed in ("json", "jsonl"):
        if json_kind is None:
            raise ConnectorError(
                f"This file is not {claimed.upper()} (it looks like delimited text): "
                "check its name or format"
            )
        fmt = claimed if "format" in overrides else json_kind
        options = {"encoding": encoding}
        if overrides.get("json_path"):
            options["json_path"] = str(overrides["json_path"])
        return Sniffed(fmt, options)
    if json_kind is not None and claimed is None:
        return Sniffed(json_kind, {"encoding": encoding})
    if claimed in ("csv", "tsv") and json_kind is not None:
        raise ConnectorError(
            f"This file is JSON, not {claimed.upper()}: check its name or format"
        )
    hint = "\t" if claimed == "tsv" else None
    delimiter = overrides.get("delimiter") or _delimiter(text, hint)
    fmt = "tsv" if delimiter == "\t" else "csv"
    return Sniffed(fmt, {"encoding": encoding, "delimiter": delimiter})


__all__ = ["FORMATS", "Sniffed", "format_from_name", "sniff"]
