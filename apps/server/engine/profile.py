"""A column profile of a table, and the table written as Parquet.

The keys follow the data.gouv.fr tabular API's profile where they can
(``nb_missing_values``, ``nb_distinct``, ``tops``, ``min``, ``max``, ``mean``,
``std``), so a profile reads the same whichever side made it.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.engine.session import EngineSession, quote_ident, quote_literal

TOPS = 10
SAMPLES = 5
_NUMERIC = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "UBIGINT",
    "UINTEGER",
    "USMALLINT",
    "UTINYINT",
)
_ORDERED = ("DATE", "TIMESTAMP", "TIME")


def _plain(value: Any) -> Any:
    """A JSON-ready value."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (list, dict, tuple)):
        return str(value)
    return value


def _is(kind: str, family: tuple) -> bool:
    return kind.upper().split("(")[0] in family or any(
        kind.upper().startswith(f) for f in family
    )


def profile(session: EngineSession, table: str) -> Dict[str, Any]:
    """``{"rows": n, "columns": {name: {...}}}`` of ``table``."""
    t = quote_ident(table)
    rows = session.fetchone(f"SELECT count(*) FROM {t}")
    total = int(rows[0]) if rows else 0
    described = session.fetchall(f"SELECT column_name, column_type FROM (DESCRIBE {t})")
    columns: Dict[str, Dict[str, Any]] = {}
    for name, kind in described:
        c = quote_ident(name)
        missing, distinct = session.fetchone(
            f"SELECT count(*) - count({c}), approx_count_distinct({c}) FROM {t}"
        ) or (0, 0)
        info: Dict[str, Any] = {
            "type": kind,
            "nb_missing_values": int(missing),
            "nb_distinct": int(distinct),
        }
        if _is(kind, _NUMERIC):
            lo, hi, mean, std = session.fetchone(
                f"SELECT min({c}), max({c}), avg({c}), stddev_samp({c}) FROM {t}"
            ) or (None, None, None, None)
            info.update(
                min=_plain(lo),
                max=_plain(hi),
                mean=None if mean is None else round(float(mean), 6),
                std=None if std is None else round(float(std), 6),
            )
        elif _is(kind, _ORDERED):
            lo, hi = session.fetchone(f"SELECT min({c}), max({c}) FROM {t}") or (
                None,
                None,
            )
            info.update(min=_plain(lo), max=_plain(hi))
        tops = session.fetchall(
            f"SELECT {c} AS v, count(*) AS n FROM {t} WHERE {c} IS NOT NULL "
            f"GROUP BY v ORDER BY n DESC, v LIMIT {TOPS}"
        )
        info["tops"] = [{"value": _plain(v), "count": int(n)} for v, n in tops]
        samples = session.fetchall(
            f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL LIMIT {SAMPLES}"
        )
        info["samples"] = [_plain(r[0]) for r in samples]
        columns[name] = info
    return {"rows": total, "columns": columns}


def write_parquet(session: EngineSession, table: str, path: Path) -> int:
    """``table`` as ZSTD Parquet at ``path`` (in the run's folder); its size."""
    target = session.path(*Path(path).resolve().relative_to(session.run_dir).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    session.execute(
        f"COPY (SELECT * FROM {quote_ident(table)}) TO {quote_literal(str(target))} "
        "(FORMAT parquet, COMPRESSION zstd)"
    )
    return target.stat().st_size


def preview_rows(
    session: EngineSession, table: str, limit: int, offset: int = 0
) -> List[Dict[str, Any]]:
    """A page of ``table``'s rows, JSON-ready."""
    t = quote_ident(table)

    def page():
        cursor = session.conn.execute(
            f"SELECT * FROM {t} LIMIT ? OFFSET ?", [limit, offset]
        )
        names = [d[0] for d in cursor.description or []]
        return [
            dict(zip(names, (_plain(v) for v in row), strict=True))
            for row in cursor.fetchall()
        ]

    return session._guarded(page)


def page_parquet(
    session: EngineSession,
    path: Path,
    *,
    offset: int,
    limit: int,
    sort: Optional[str] = None,
    descending: bool = False,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
) -> Dict[str, Any]:
    """A page of a Parquet file's rows: sorted by one column, filtered on one
    column containing some text (case-insensitive). Column names come checked
    by the caller and are quoted; the value is a parameter."""
    params: List[Any] = [str(path)]
    where = ""
    if filter_column and filter_value not in (None, ""):
        where = f"WHERE contains(lower(CAST({quote_ident(filter_column)} AS VARCHAR)), lower(?))"
        params.append(filter_value)
    order = ""
    if sort:
        order = (
            f"ORDER BY {quote_ident(sort)} {'DESC' if descending else 'ASC'} NULLS LAST"
        )
    total = session.fetchone(f"SELECT count(*) FROM read_parquet(?) {where}", params)

    def page():
        cursor = session.conn.execute(
            f"SELECT * FROM read_parquet(?) {where} {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        columns = [d[0] for d in cursor.description or []]
        rows = [
            dict(zip(columns, (_plain(v) for v in row), strict=True))
            for row in cursor.fetchall()
        ]
        return columns, rows

    columns, rows = session._guarded(page)
    return {
        "total": int(total[0]) if total else 0,
        "offset": offset,
        "limit": limit,
        "columns": columns,
        "rows": rows,
    }


def split_parquet(
    session: EngineSession, data: Path, target: Path, file_bytes: int
) -> List[Path]:
    """``data`` rewritten as ZSTD Parquet files of about ``file_bytes`` each, in
    ``target`` (in the run's folder)."""
    session.execute(
        f"COPY (SELECT * FROM read_parquet({quote_literal(str(data))})) "
        f"TO {quote_literal(str(target))} "
        f"(FORMAT parquet, COMPRESSION zstd, FILE_SIZE_BYTES {int(file_bytes)})"
    )
    return sorted(target.rglob("*.parquet"))


def iter_rows(session: EngineSession, table: str, batch: int = 5000):
    """Every row of ``table`` as a dict, in the table's order, a batch at a time."""
    offset = 0
    while True:
        page = preview_rows(session, table, batch, offset)
        if not page:
            return
        yield from page
        offset += len(page)
