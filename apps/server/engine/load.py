"""Load a fetched data source into a typed DuckDB table, ``source``.

Text (CSV, TSV) is read as text first, then each column gets the type every
one of its values takes — a column whose values have leading zeros (a commune
code, a postcode) or French thousands separators (``1 284``) stays text unless
a cast step says otherwise. JSON, JSON Lines and Parquet keep their own types;
an Excel sheet is read with openpyxl. Column names are trimmed and made
unique; the schema keeps the original names.
"""

import codecs
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from server.connectors.base import FetchResult
from server.engine.session import (
    EngineError,
    EngineSession,
    quote_ident,
    quote_literal,
)

TABLE = "source"
# The rows a text column's type is guessed from (then checked on every row).
_TYPE_SAMPLE = 100_000
_TEXT_TYPES = ("BIGINT", "DOUBLE", "DATE", "TIMESTAMP", "BOOLEAN")


@dataclass
class Column:
    name: str
    original: str
    type: str


@dataclass
class Loaded:
    rows: int
    columns: List[Column] = field(default_factory=list)

    def schema(self) -> List[Dict[str, str]]:
        return [
            {"name": c.name, "original": c.original, "type": c.type}
            for c in self.columns
        ]


def normalise_names(names: List[str]) -> List[str]:
    """Trimmed, never empty, unique (``name``, ``name_2``…)."""
    out: List[str] = []
    seen: set = set()
    for i, raw in enumerate(names, 1):
        name = re.sub(r"\s+", " ", str(raw or "")).strip() or f"column_{i}"
        candidate, n = name, 2
        while candidate.lower() in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate.lower())
        out.append(candidate)
    return out


# --- text ----------------------------------------------------------------------


def _utf8_copy(session: EngineSession, path: Path, encoding: str) -> Path:
    """A UTF-8 copy of a text file in another encoding, made in Python (DuckDB
    reads UTF-8 and Latin-1 only; Windows-1252 differs from Latin-1)."""
    if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        return path
    target = session.path("raw", path.name + ".utf8")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError:
        raise EngineError(f"Unknown encoding '{encoding}'") from None
    try:
        with path.open("rb") as src, target.open("w", encoding="utf-8") as out:
            while chunk := src.read(1024 * 1024):
                out.write(decoder.decode(chunk))
            out.write(decoder.decode(b"", final=True))
    except UnicodeDecodeError as exc:
        raise EngineError(
            f"The file is not {encoding}: byte {exc.start} can't be read. "
            "Pick another encoding"
        ) from None
    return target


_COLUMNS_MISMATCH = re.compile(
    r"Expected Number of Columns:\s*(\d+)\s*Found:\s*(\d+)", re.IGNORECASE
)
_LINE = re.compile(r"Line:\s*(\d+)", re.IGNORECASE)


def _csv_error(exc: duckdb.Error) -> EngineError:
    text = str(exc)
    match = _COLUMNS_MISMATCH.search(text)
    line = _LINE.search(text)
    if match and line:
        expected, found = match.groups()
        return EngineError(
            f"Line {line.group(1)}: {expected} columns expected, {found} or more found"
        )
    if "unicode" in text.lower() or "utf-8" in text.lower():
        return EngineError("The file is not UTF-8 or Latin-1: pick its encoding")
    where = f" (line {line.group(1)})" if line else ""
    return EngineError(f"The file can't be read as delimited text{where}")


def _load_text(session: EngineSession, result: FetchResult) -> List[str]:
    """``raw_text``, every column as text, named from the header; the header."""
    options = result.options
    delimiter = options.get("delimiter") or ("\t" if result.format == "tsv" else ",")
    files = [
        _utf8_copy(session, p, options.get("encoding") or "utf-8") for p in result.files
    ]
    with files[0].open("r", encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream, delimiter=delimiter), None)
    if not header:
        raise EngineError("The file has no header line")
    names = normalise_names(header)
    columns = "{" + ", ".join(f"{quote_literal(n)}: 'VARCHAR'" for n in names) + "}"
    listing = "[" + ", ".join(quote_literal(str(p)) for p in files) + "]"
    try:
        session.execute(
            f"CREATE TABLE raw_text AS SELECT * FROM read_csv({listing}, "
            f"delim={quote_literal(delimiter)}, header=true, auto_detect=false, "
            f"columns={columns}, quote='\"', escape='\"', strict_mode=true, "
            "null_padding=false)"
        )
    except duckdb.Error as exc:
        raise _csv_error(exc) from None
    _type_text_columns(session)
    return header


def _type_text_columns(session: EngineSession) -> None:
    """``source`` from ``raw_text``: each column the narrowest type all of its
    values take, text when a value would change (leading zeros, separators).
    One scan of the table gives every column's counts."""
    names = [
        r[0] for r in session.fetchall("SELECT column_name FROM (DESCRIBE raw_text)")
    ]
    clean = normalise_names(names)
    probes: List[str] = []
    for raw in names:
        trimmed = f"NULLIF(TRIM({quote_ident(raw)}), '')"
        probes.append(f"count({trimmed})")
        # Leading zeros ("01001", "-02"): plain string tests, cheaper than a regex.
        unsigned = f"ltrim({trimmed}, '-')"
        probes.append(
            f"count(*) FILTER (WHERE left({unsigned}, 1) = '0' "
            f"AND substr({unsigned}, 2, 1) BETWEEN '0' AND '9')"
        )
        # Not a plain integer: "998.0", "1e3", "12 000"…
        probes.append(
            f"count(*) FILTER (WHERE {trimmed} IS NOT NULL "
            f"AND (TRY_CAST({trimmed} AS BIGINT) IS NULL "
            f"OR NOT (ltrim({unsigned}, '0123456789') = '')))"
        )
        for kind in _TEXT_TYPES:
            probes.append(
                f"count(*) FILTER (WHERE {trimmed} IS NOT NULL "
                f"AND TRY_CAST({trimmed} AS {kind}) IS NULL)"
            )
    # The candidates from a sample, then one check of the chosen types over
    # every row (below): two scans whatever the number of columns.
    counts = (
        session.fetchone(
            f"SELECT {', '.join(probes)} FROM (SELECT * FROM raw_text LIMIT {_TYPE_SAMPLE})"
        )
        or ()
    )
    width = 3 + len(_TEXT_TYPES)
    selects: List[str] = []
    chosen_types: List[str] = []
    for i in range(len(names)):
        present, zeros, not_integers, *failures = counts[i * width : (i + 1) * width]
        chosen = "VARCHAR"
        if present and not zeros:
            for kind, failed in zip(_TEXT_TYPES, failures, strict=True):
                if kind == "BIGINT" and not_integers:
                    continue  # "998.0" is a decimal number, not an integer
                if failed == 0:
                    chosen = kind
                    break
        chosen_types.append(chosen)
    # Every row must take the type the sample chose; a column with one that
    # doesn't (or a leading zero further down) stays text.
    checks: List[str] = []
    for raw, kind in zip(names, chosen_types, strict=True):
        trimmed = f"NULLIF(TRIM({quote_ident(raw)}), '')"
        if kind == "VARCHAR":
            checks.append("0")
            continue
        unsigned = f"ltrim({trimmed}, '-')"
        zero = (
            f"(left({unsigned}, 1) = '0' AND substr({unsigned}, 2, 1) BETWEEN '0' AND '9')"
            if kind in ("BIGINT", "DOUBLE")
            else "false"
        )
        checks.append(
            f"count(*) FILTER (WHERE {trimmed} IS NOT NULL AND "
            f"(TRY_CAST({trimmed} AS {kind}) IS NULL OR {zero}))"
        )
    failed_rows = session.fetchone(f"SELECT {', '.join(checks)} FROM raw_text") or ()
    for raw, name, kind, failed in zip(
        names, clean, chosen_types, failed_rows, strict=True
    ):
        col = quote_ident(raw)
        if kind == "VARCHAR" or failed:
            expr = col  # the text as written (spaces included)
        else:
            expr = f"TRY_CAST(NULLIF(TRIM({col}), '') AS {kind})"
        selects.append(f"{expr} AS {quote_ident(name)}")
    session.execute(
        f"CREATE TABLE {TABLE} AS SELECT {', '.join(selects)} FROM raw_text"
    )
    session.execute("DROP TABLE raw_text")


# --- JSON, Parquet, Excel ------------------------------------------------------


def _json_records(session: EngineSession, path: Path, json_path: str) -> Path:
    """The array at ``json_path`` (``data.records``) of a JSON document, as JSON
    Lines in the run's folder."""
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineError(
            f"The file is not valid JSON ({exc.__class__.__name__})"
        ) from None
    node: Any = document
    for part in [p for p in json_path.strip().strip(".").split(".") if p]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise EngineError(f"No '{json_path}' in this JSON document")
    if not isinstance(node, list):
        raise EngineError(f"'{json_path}' is not a list of records")
    target = session.path("raw", path.name + ".records.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as out:
        for record in node:
            out.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return target


def _load_json(session: EngineSession, result: FetchResult) -> None:
    files = list(result.files)
    fmt = "newline_delimited" if result.format == "jsonl" else "auto"
    json_path = result.options.get("json_path")
    if json_path:
        files = [_json_records(session, p, json_path) for p in files]
        fmt = "newline_delimited"
    listing = "[" + ", ".join(quote_literal(str(p)) for p in files) + "]"
    try:
        session.execute(
            f"CREATE TABLE {TABLE} AS SELECT * FROM read_json({listing}, "
            f"format={quote_literal(fmt)}, records=true)"
        )
    except duckdb.Error as exc:
        raise EngineError(
            f"The file can't be read as {result.format.upper()} records: "
            + str(exc).splitlines()[0][:200]
        ) from None


def _load_parquet(session: EngineSession, result: FetchResult) -> None:
    listing = "[" + ", ".join(quote_literal(str(p)) for p in result.files) + "]"
    try:
        session.execute(
            f"CREATE TABLE {TABLE} AS SELECT * FROM read_parquet({listing})"
        )
    except duckdb.Error:
        raise EngineError("The file can't be read as Parquet") from None


def _cell_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, (date, time)):
        return "date" if isinstance(value, date) else "text"
    return "text"


def _load_xlsx(session: EngineSession, result: FetchResult) -> None:
    """One sheet through openpyxl (read-only, defusedxml when installed), then
    a Parquet file in the run's folder that DuckDB reads."""
    import openpyxl
    import pyarrow as pa
    import pyarrow.parquet as pq

    try:
        book = openpyxl.load_workbook(result.files[0], read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — a broken workbook, whatever the error
        raise EngineError("The file can't be read as an Excel workbook") from None
    try:
        sheet_name = result.options.get("sheet")
        sheet = book[sheet_name] if sheet_name else book.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            raise EngineError("The sheet is empty")
        names = normalise_names([str(h) if h is not None else "" for h in header])
        values: List[List[Any]] = [[] for _ in names]
        for row in rows:
            if row is None or all(v is None for v in row):
                continue
            for i in range(len(names)):
                values[i].append(row[i] if i < len(row) else None)
    finally:
        book.close()
    arrays = {}
    for name, column in zip(names, values, strict=True):
        kinds = {_cell_kind(v) for v in column if v is not None}
        if kinds == {"int"}:
            arrays[name] = pa.array(column, type=pa.int64())
        elif kinds <= {"int", "float"} and kinds:
            arrays[name] = pa.array(
                [float(v) if v is not None else None for v in column], type=pa.float64()
            )
        elif kinds == {"bool"}:
            arrays[name] = pa.array(column, type=pa.bool_())
        elif kinds == {"datetime"}:
            arrays[name] = pa.array(column, type=pa.timestamp("us"))
        else:
            arrays[name] = pa.array(
                [None if v is None else str(v) for v in column], type=pa.string()
            )
    target = session.path("raw", "sheet.parquet")
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(arrays), target)
    session.execute(
        f"CREATE TABLE {TABLE} AS SELECT * FROM read_parquet({quote_literal(str(target))})"
    )


def _rename_columns(session: EngineSession) -> List[Column]:
    """Make ``source``'s names unique and trimmed, keeping the originals."""
    described = session.fetchall(
        f"SELECT column_name, column_type FROM (DESCRIBE {TABLE})"
    )
    originals = [r[0] for r in described]
    clean = normalise_names(originals)
    for original, name in zip(originals, clean, strict=True):
        if original != name:
            session.execute(
                f"ALTER TABLE {TABLE} RENAME COLUMN {quote_ident(original)} TO {quote_ident(name)}"
            )
    return [
        Column(n, o, t)
        for n, o, (_, t) in zip(clean, originals, described, strict=True)
    ]


def load(session: EngineSession, result: FetchResult) -> Loaded:
    """Load ``result``'s files as the table ``source``."""
    if not result.files:
        raise EngineError("Nothing was fetched")
    header: Optional[List[str]] = None
    if result.format in ("csv", "tsv"):
        header = _load_text(session, result)
    elif result.format in ("json", "jsonl"):
        _load_json(session, result)
    elif result.format == "parquet":
        _load_parquet(session, result)
    elif result.format == "xlsx":
        _load_xlsx(session, result)
    else:
        raise EngineError(f"Unknown format '{result.format}'")
    columns = _rename_columns(session)
    if header and len(header) == len(columns):
        # Text columns were named from the header before typing.
        for column, original in zip(columns, header, strict=True):
            column.original = original
    count = session.fetchone(f"SELECT count(*) FROM {TABLE}")
    return Loaded(rows=int(count[0]) if count else 0, columns=columns)


def load_cached(session: EngineSession, path: Path) -> int:
    """``source`` from a Parquet file this engine wrote (a preview's cache);
    its row count."""
    session.execute(
        f"CREATE TABLE {TABLE} AS SELECT * FROM read_parquet({quote_literal(str(path))})"
    )
    return row_count(session)


def row_count(session: EngineSession, table: str = TABLE) -> int:
    count = session.fetchone(f"SELECT count(*) FROM {quote_ident(table)}")
    return int(count[0]) if count else 0
