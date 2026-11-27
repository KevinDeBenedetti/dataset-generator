"""The SQL dump connector (#319): a ``.sql`` or ``.sql.gz`` file of ``CREATE
TABLE`` and ``INSERT`` statements (or ``COPY … FROM stdin`` blocks), loaded into
a throwaway DuckDB confined to the run's folder; one of its tables is the data.

Parse, don't trust: the dump is cut into statements, and only three kinds are
ever executed — ``CREATE TABLE`` with its columns, ``INSERT … VALUES`` of
literals, and ``COPY … FROM stdin`` data, whose rows are loaded as values.
The housekeeping a dump tool writes around them (``SET``, ``LOCK TABLES``,
``CREATE INDEX``, ``ALTER TABLE … ADD CONSTRAINT``, ``GRANT``…) is skipped
without running; anything else — ``DROP DATABASE``, ``COPY … TO``, a
``PROGRAM``, a function, an extension, ``ATTACH``, a psql ``\\`` command — is
refused before a single statement runs. Statements are parsed with sqlglot in
the dump's dialect and written back as DuckDB SQL; nothing here ever touches
the app's database.
"""

import gzip
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from server.connectors.base import (
    ConnectorError,
    ConnectorSpec,
    FetchResult,
    Limits,
    Provenance,
    sha256_of,
)
from server.core.i18n import tr
from server.services.credentials import Credentials

KIND = "sql_dump"
Dialect = Literal["postgres", "mysql", "sqlite"]
MAX_STATEMENTS = 2_000_000
# Rows of a COPY block loaded at once.
COPY_BATCH = 50_000


class SqlDumpTable(BaseModel):
    name: str
    rows: int


class SqlDumpConfig(BaseModel):
    filename: str = Field(..., description="The file's name, as uploaded")
    stored_name: str = Field(..., description="Its name in the draft store")
    sha256: str
    bytes: int
    dialect: Dialect
    tables: List[SqlDumpTable] = Field(default_factory=list, max_length=500)
    # The table that is the data (the only one when the dump has one).
    table: Optional[str] = Field(None, max_length=200)


def is_dump(filename: str) -> bool:
    name = filename.lower()
    return name.endswith(".sql") or name.endswith(".sql.gz")


# ─── Reading the dump ────────────────────────────────────────────────────────


def read_text(path: Path, max_bytes: int) -> str:
    """The dump's text (gunzipped), at most ``max_bytes`` once decompressed."""
    with path.open("rb") as raw:
        magic = raw.read(5)
    if magic.startswith(b"PGDMP"):
        raise ConnectorError(
            "This is a pg_dump custom-format archive (-Fc): export it as plain "
            "SQL instead (pg_dump -Fp, or pg_restore -f dump.sql)"
        )
    opener = gzip.open if magic[:2] == b"\x1f\x8b" else open
    with opener(path, "rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ConnectorError(
            f"The dump is larger than {max_bytes // 1024**2} MB once decompressed"
        )
    return data.decode("utf-8", errors="replace")


def detect_dialect(text: str) -> Dialect:
    head = text[:200_000]
    if re.search(r"^COPY |pg_catalog\.|^SET search_path", head, re.M):
        return "postgres"
    if "`" in head or re.search(r"ENGINE\s*=|^LOCK TABLES", head, re.M | re.I):
        return "mysql"
    if re.search(r"^PRAGMA |sqlite_sequence", head, re.M):
        return "sqlite"
    return "postgres"


# What may sit between statements, or inside one without ending it.
def _token_re(dialect: Dialect) -> "re.Pattern[str]":
    """Quotes, comments and ``;``. Each token that starts always matches (an
    unterminated one runs to the end of the text), so a search stays linear
    whatever the dump holds."""
    quote = (
        r"'(?:[^'\\]|\\.|'')*(?:'|\Z)"
        if dialect == "mysql"
        else r"(?:[eE]'(?:[^'\\]|\\.|'')*(?:'|\Z)|'(?:[^']|'')*(?:'|\Z))"
    )
    return re.compile(
        quote
        + r'|"(?:[^"]|"")*(?:"|\Z)'
        + r"|`(?:[^`]|``)*(?:`|\Z)"
        + r"|--[^\n]*"
        + r"|/\*.*?(?:\*/|\Z)"
        # Dollar quotes are PostgreSQL's: $$…$$, $body$…$body$.
        + (
            r"|\$\$.*?(?:\$\$|\Z)|\$(?P<tag>[A-Za-z_]\w*)\$.*?(?:\$(?P=tag)\$|\Z)"
            if dialect == "postgres"
            else ""
        )
        + r"|;",
        re.S,
    )


# The psql meta-commands pg_dump itself writes (\restrict and \unrestrict in
# recent releases, \connect): skipped.
_PSQL_SKIPPED = re.compile(
    r"^\\(?:restrict|unrestrict|connect|c|encoding|set\s+ON_ERROR_STOP)\b"
)


_COPY_STDIN = re.compile(
    r"^COPY\s+(?P<table>[\w.\"]+)\s*(?:\((?P<cols>[^)]*)\))?\s+FROM\s+stdin\b",
    re.I,
)


@dataclass
class Copy:
    table: str
    columns: List[str]
    rows: List[List[Optional[str]]] = field(default_factory=list)


def statements(
    text: str, dialect: Dialect, deadline: Optional[float] = None
) -> Iterator[Tuple[str, Optional[Copy]]]:
    """The dump's statements, comments dropped; a ``COPY … FROM stdin`` comes
    with its data rows. A psql meta-command other than pg_dump's own is
    refused here."""
    token = _token_re(dialect)
    pos = 0
    start = 0
    n = len(text)
    # Nothing but blanks and comments since the statement began.
    fresh = True
    while pos < n:
        if deadline is not None and time.monotonic() > deadline:
            raise ConnectorError("The dump took too long to read")
        if fresh:
            at = _skip_space(text, pos)
            if text.startswith("\\", at):
                eol = text.find("\n", at)
                eol = n if eol < 0 else eol
                line = text[at:eol]
                if not _PSQL_SKIPPED.match(line):
                    raise ConnectorError(
                        f"The dump runs a psql command ({line[:40]}): refused"
                    )
                pos = start = min(eol + 1, n)
                continue
        match = token.search(text, pos)
        if match is None:
            break
        piece = match.group(0)
        blank_gap = not text[pos : match.start()].strip()
        if piece == ";":
            stmt = _strip_comments(text[start : match.start()], token).strip()
            pos = start = match.end()
            fresh = True
            if not stmt:
                continue
            copy = _COPY_STDIN.match(stmt)
            if copy:
                data, pos = _copy_data(text, pos)
                start = pos
                yield (
                    stmt,
                    Copy(
                        table=_unquote(copy.group("table")),
                        columns=[
                            _unquote(c.strip())
                            for c in (copy.group("cols") or "").split(",")
                            if c.strip()
                        ],
                        rows=data,
                    ),
                )
            else:
                yield stmt, None
        else:
            fresh = fresh and blank_gap and piece.startswith(("--", "/*"))
            pos = match.end()
    tail = _strip_comments(text[start:], token).strip()
    if tail:
        yield tail, None


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\r\n":
        pos += 1
    return pos


def _strip_comments(stmt: str, token: "re.Pattern[str]") -> str:
    if "--" not in stmt and "/*" not in stmt:
        return stmt
    out: List[str] = []
    last = 0
    for match in token.finditer(stmt):
        piece = match.group(0)
        if piece.startswith("--") or piece.startswith("/*"):
            out.append(stmt[last : match.start()])
            out.append(" ")
            last = match.end()
    out.append(stmt[last:])
    return "".join(out)


def _unquote(name: str) -> str:
    name = name.split(".")[-1].strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in '"`':
        return name[1:-1].replace(name[0] * 2, name[0])
    return name


_COPY_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}


def _copy_field(value: str) -> Optional[str]:
    if value == "\\N":
        return None
    if "\\" not in value:
        return value
    return re.sub(r"\\(.)", lambda m: _COPY_ESCAPES.get(m.group(1), m.group(1)), value)


def _copy_data(text: str, pos: int) -> Tuple[List[List[Optional[str]]], int]:
    """The rows of the COPY block after ``pos``, up to its ``\\.`` line."""
    newline = text.find("\n", pos)
    if newline < 0:
        raise ConnectorError("A COPY block of the dump has no data")
    begin = newline + 1
    end = text.find("\n\\.", begin - 1)
    if end < 0:
        raise ConnectorError("A COPY block of the dump never ends (no \\. line)")
    block = text[begin:end] if end >= begin else ""
    rows = [
        [_copy_field(v) for v in line.split("\t")]
        for line in block.split("\n")
        if line != ""
    ]
    after = text.find("\n", end + 1)
    return rows, (after + 1 if after >= 0 else len(text))


# ─── Which statements run ────────────────────────────────────────────────────

# Housekeeping of pg_dump, mysqldump and sqlite3 .dump: never executed.
_SKIPPED = re.compile(
    r"^(?:SET\b|LOCK\s+TABLES|UNLOCK\s+TABLES|BEGIN\b|COMMIT\b|START\s+TRANSACTION"
    r"|END\b|ROLLBACK\b|SAVEPOINT\b|RELEASE\b"
    r"|SELECT\s+pg_catalog\.(?:set_config|setval)\s*\("
    r"|ALTER\s+(?:TABLE|SEQUENCE|SCHEMA|INDEX|TYPE)\b|CREATE\s+(?:UNIQUE\s+)?INDEX\b"
    r"|CREATE\s+SEQUENCE\b|CREATE\s+SCHEMA\b|COMMENT\s+ON\b|GRANT\b|REVOKE\b"
    r"|DROP\s+(?:TABLE|SEQUENCE|INDEX|VIEW)\b|PRAGMA\s+foreign_keys\b"
    r"|DELETE\s+FROM\s+sqlite_sequence\b|INSERT\s+INTO\s+\"?sqlite_sequence\b"
    r"|ANALYZE\b|VACUUM\b|USE\b)",
    re.I,
)
_CREATE_TABLE = re.compile(r"^CREATE\s+(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?TABLE\b", re.I)
_INSERT = re.compile(r"^(?:INSERT|REPLACE)\s+(?:IGNORE\s+)?INTO\b", re.I)


def _refusal(stmt: str) -> str:
    words = " ".join(stmt.split()[:3])
    return f"The dump holds a statement that is not loaded: {words[:60]} (refused)"


def _literal_only(node: Any) -> bool:
    """Values made of literals only: no function, no column, no subquery."""
    from sqlglot import exp

    allowed = (
        exp.Values,
        exp.Literal,
        exp.Null,
        exp.Boolean,
        exp.Neg,
        exp.Paren,
        exp.Tuple,
        exp.Cast,
        exp.DataType,
        exp.DataTypeParam,
        exp.Identifier,
        exp.Var,
        exp.HexString,
        exp.BitString,
        exp.ByteString,
        exp.RawString,
        exp.National,
    )
    for sub in node.walk():
        if not isinstance(sub, allowed):
            return False
        if isinstance(sub, exp.Identifier) and not isinstance(
            sub.parent, (exp.DataType, exp.DataTypeParam)
        ):
            return False
    return True


# Types whose parameters mean something here: DECIMAL(10, 2).
_SIZED = {"DECIMAL", "UDECIMAL", "BIGDECIMAL"}


def _bare_columns(schema: Any) -> None:
    """A table's columns with their types only: keys, indexes, defaults and
    constraints belong to the database the dump came from (and a default can
    call a function)."""
    from sqlglot import exp

    for node in list(schema.expressions):
        if not isinstance(node, exp.ColumnDef):
            node.pop()
            continue
        node.set("constraints", [])
        kind = node.args.get("kind")
        # VARCHAR(5), INT(11): DuckDB keeps no length, and refuses some.
        if isinstance(kind, exp.DataType) and kind.this.name not in _SIZED:
            kind.set("expressions", [])


def plan(
    text: str, dialect: Dialect, deadline: Optional[float] = None
) -> List[Tuple[str, Any]]:
    """The dump's loading steps — ``("sql", duckdb_sql)`` or ``("copy", Copy)``
    — or a ConnectorError naming the first statement refused. Nothing runs."""
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import SqlglotError

    steps: List[Tuple[str, Any]] = []
    for count, (stmt, copy) in enumerate(statements(text, dialect, deadline)):
        if count >= MAX_STATEMENTS:
            raise ConnectorError(f"The dump has more than {MAX_STATEMENTS} statements")
        if copy is not None:
            steps.append(("copy", copy))
            continue
        if _SKIPPED.match(stmt):
            continue
        is_create = bool(_CREATE_TABLE.match(stmt))
        if not is_create and not _INSERT.match(stmt):
            raise ConnectorError(_refusal(stmt))
        try:
            tree = sqlglot.parse_one(stmt, read=dialect)
        except SqlglotError as exc:
            raise ConnectorError(
                f"A statement of the dump could not be read ({' '.join(stmt.split()[:3])}): "
                f"{str(exc).splitlines()[0][:120]}"
            ) from None
        if is_create:
            if (
                not isinstance(tree, exp.Create)
                or str(tree.args.get("kind") or "").upper() != "TABLE"
                or tree.args.get("expression") is not None
                or not isinstance(tree.this, exp.Schema)
            ):
                raise ConnectorError(_refusal(stmt))
            _bare_columns(tree.this)
        else:
            values = tree.args.get("expression")
            if not isinstance(tree, exp.Insert) or not isinstance(values, exp.Values):
                raise ConnectorError(_refusal(stmt))
            if not _literal_only(values):
                raise ConnectorError(
                    "An INSERT of the dump computes its values (a function or a "
                    "query): only literal values are loaded"
                )
            tree.set("alternative", None)
            tree.set("ignore", None)
        # One database here: a table is known by its name alone.
        for table in tree.find_all(exp.Table):
            table.set("db", None)
            table.set("catalog", None)
        steps.append(("sql", tree.sql(dialect="duckdb")))
    if not any(
        kind == "sql" and sql.upper().startswith("CREATE") for kind, sql in steps
    ):
        raise ConnectorError("The dump creates no table")
    return steps


# ─── Loading ─────────────────────────────────────────────────────────────────


def load(
    session: Any, steps: List[Tuple[str, Any]], deadline: float
) -> List[SqlDumpTable]:
    """Run ``steps`` in the engine session; the tables made, with their rows."""
    from server.engine.session import quote_ident

    for kind, step in steps:
        if time.monotonic() > deadline:
            raise ConnectorError("The dump took too long to load")
        try:
            if kind == "sql":
                session.execute(step)
            else:
                _load_copy(session, step, quote_ident)
        except ConnectorError:
            raise
        except Exception as exc:  # duckdb's own errors, in words for the user
            message = str(exc).splitlines()[0][:200]
            raise ConnectorError(f"The dump could not be loaded: {message}") from None
    names = [
        r[0]
        for r in session.fetchall("SELECT table_name FROM duckdb_tables() ORDER BY 1")
    ]
    return [
        SqlDumpTable(
            name=name,
            rows=int(session.fetchone(f"SELECT count(*) FROM {quote_ident(name)}")[0]),
        )
        for name in names
    ]


def _load_copy(session: Any, copy: Copy, quote_ident) -> None:
    """A COPY block's rows, as text values the table's types cast."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns = copy.columns or [
        r[0]
        for r in session.fetchall(
            "SELECT column_name FROM duckdb_columns() WHERE table_name = ? "
            "ORDER BY column_index",
            [copy.table],
        )
    ]
    if not columns:
        raise ConnectorError(
            f"COPY into '{copy.table}', a table the dump never creates"
        )
    target = session.path("tmp", "copy.parquet")
    for begin in range(0, max(len(copy.rows), 1), COPY_BATCH):
        batch = copy.rows[begin : begin + COPY_BATCH]
        if not batch:
            return
        if any(len(row) != len(columns) for row in batch):
            raise ConnectorError(
                f"A COPY row of '{copy.table}' does not have {len(columns)} values"
            )
        arrays = [
            pa.array([row[i] for row in batch], pa.string())
            for i in range(len(columns))
        ]
        pq.write_table(
            pa.Table.from_arrays(arrays, names=[f"c{i}" for i in range(len(columns))]),
            target,
        )
        cols = ", ".join(quote_ident(c) for c in columns)
        picks = ", ".join(f"c{i}" for i in range(len(columns)))
        session.execute(
            f"INSERT INTO {quote_ident(copy.table)} ({cols}) "
            f"SELECT {picks} FROM read_parquet(?)",
            [str(target)],
        )
    target.unlink(missing_ok=True)


def load_dump(
    path: Path, work_dir: Path, limits: Limits, dialect: Optional[Dialect] = None
) -> Tuple[Any, Dialect, List[SqlDumpTable]]:
    """The dump at ``path`` loaded in a sandboxed DuckDB over ``work_dir``:
    the open session (the caller closes it), the dialect and the tables."""
    from server.engine.session import EngineSession

    deadline = time.monotonic() + limits.timeout_s
    text = read_text(path, limits.max_bytes)
    dialect = dialect or detect_dialect(text)
    steps = plan(text, dialect, deadline)
    del text
    session = EngineSession(work_dir, timeout_s=limits.timeout_s)
    try:
        tables = load(session, steps, deadline)
    except BaseException:
        session.close()
        raise
    return session, dialect, tables


def describe(
    path: Path, filename: str, work_dir: Path, limits: Limits
) -> Dict[str, Any]:
    """The upload's config once stored at ``path``: its dialect and tables."""
    session, dialect, tables = load_dump(path, work_dir, limits)
    session.close()
    return SqlDumpConfig(
        filename=Path(filename).name[:200] or "dump.sql",
        stored_name=path.name,
        sha256=sha256_of([path]),
        bytes=path.stat().st_size,
        dialect=dialect,
        tables=tables,
        table=tables[0].name if len(tables) == 1 else None,
    ).model_dump()


class SqlDumpConnector:
    kind = KIND
    config_model = SqlDumpConfig

    def spec(self, locale: str) -> ConnectorSpec:
        return ConnectorSpec(
            kind=KIND,
            title=tr(locale, "connectors.sql_dump.title", "SQL dump"),
            description=tr(
                locale,
                "connectors.sql_dump.description",
                "A .sql or .sql.gz dump (PostgreSQL, MySQL, SQLite): one of its tables",
            ),
            config_schema=SqlDumpConfig.model_json_schema(),
            created_by_upload=True,
        )

    async def fetch(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        creds: Credentials,
        dest: Path,
        limits: Limits,
    ) -> FetchResult:
        import asyncio

        cfg = SqlDumpConfig.model_validate(config)
        target = await asyncio.to_thread(
            self._export, owner_id, source_id, cfg, dest, limits
        )
        return FetchResult(
            files=[target],
            format="parquet",
            options={},
            provenance=Provenance(
                connector=KIND,
                fetched_at=datetime.now(timezone.utc),
                sha256=cfg.sha256,
                bytes=cfg.bytes,
                resource_id=f"{cfg.filename}#{cfg.table}",
            ),
            version=cfg.sha256,
        )

    @staticmethod
    def _export(
        owner_id: str, source_id: str, cfg: SqlDumpConfig, dest: Path, limits: Limits
    ) -> Path:
        from server.engine.session import quote_ident, quote_literal
        from server.services.draft_store import SOURCES_DIR, get_store

        if not cfg.table:
            raise ConnectorError(
                "Pick the dump's table to use: " + ", ".join(t.name for t in cfg.tables)
            )
        stored = get_store().path(owner_id, SOURCES_DIR, source_id, cfg.stored_name)
        if not stored.is_file():
            raise ConnectorError("The uploaded dump is gone: upload it again")
        if sha256_of([stored]) != cfg.sha256:
            raise ConnectorError("The uploaded dump changed: upload it again")
        work = dest / "sql_dump"
        session, _, tables = load_dump(stored, work, limits, cfg.dialect)
        try:
            if cfg.table not in {t.name for t in tables}:
                raise ConnectorError(f"The dump has no table '{cfg.table}'")
            target = session.path("table.parquet")
            session.execute(
                f"COPY (SELECT * FROM {quote_ident(cfg.table)}) "
                f"TO {quote_literal(str(target))} (FORMAT parquet)"
            )
        finally:
            session.close()
        out = dest / "table.parquet"
        shutil.move(str(target), out)
        shutil.rmtree(work, ignore_errors=True)
        return out

    async def unchanged(
        self,
        owner_id: str,
        source_id: str,
        config: Dict[str, Any],
        version: Optional[str],
    ) -> bool:
        """An uploaded dump never changes: another dump is another data source."""
        return bool(version) and version == config.get("sha256")

    def fingerprint(self, result: FetchResult) -> str:
        return result.provenance.sha256
