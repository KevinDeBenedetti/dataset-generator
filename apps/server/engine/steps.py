"""Recipe steps: JSON, validated, compiled to one DuckDB query (ADR 0003).

Each step reads the table the previous one made (a CTE chain over ``source``).
Every column a step names is checked against the schema at that point — an
unknown one is a :class:`StepError` naming the step — and reaches SQL only
through :func:`quote_ident`; every value is a bound parameter. No user string
is ever concatenated into SQL.

A hidden row number (``__dg_row``) rides along so ``dedup`` can keep the first
or the last occurrence in the file's order; the final query drops it.
"""

import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from server.engine.session import EngineError, EngineSession, quote_ident

ROW = "__dg_row"
MAX_STEPS = 100

CastTarget = Literal["integer", "double", "date", "timestamp", "boolean", "text"]
_SQL_TYPES = {
    "integer": "BIGINT",
    "double": "DOUBLE",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "boolean": "BOOLEAN",
    "text": "VARCHAR",
}


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Select(_Step):
    op: Literal["select"]
    columns: List[str] = Field(..., min_length=1, max_length=2000)


class Rename(_Step):
    op: Literal["rename"]
    mapping: Dict[str, str] = Field(..., min_length=1)


class Cast(_Step):
    op: Literal["cast"]
    column: str
    to: CastTarget
    format: Optional[str] = Field(
        None, max_length=64, description="strptime format, e.g. %d/%m/%Y"
    )
    decimal_comma: bool = Field(
        False, description="Numbers written 1 284,5: spaces dropped, comma as point"
    )
    on_error: Literal["null", "fail"] = "null"


class Filter(_Step):
    op: Literal["filter"]
    column: str
    operator: Literal[
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "in",
        "not_in",
        "contains",
        "is_null",
        "not_null",
    ]
    value: Any = None


class Dedup(_Step):
    op: Literal["dedup"]
    columns: List[str] = Field(default_factory=list)
    keep: Literal["first", "last"] = "first"


class Mask(_Step):
    op: Literal["mask"]
    column: str
    method: Literal["drop", "hash", "redact", "truncate"]
    keep: int = Field(1, ge=0, le=1000, description="truncate: characters kept")


class Trim(_Step):
    op: Literal["trim"]
    columns: List[str] = Field(default_factory=list)


class Limit(_Step):
    op: Literal["limit"]
    rows: int = Field(..., ge=0, le=1_000_000_000)


Step = Annotated[
    Union[Select, Rename, Cast, Filter, Dedup, Mask, Trim, Limit],
    Field(discriminator="op"),
]
_steps_adapter = TypeAdapter(List[Step])


class StepError(EngineError):
    """A step that can't apply: ``index`` is its position (0-based)."""

    def __init__(self, index: int, message: str):
        super().__init__(f"Step {index + 1}: {message}")
        self.index = index
        self.detail = message


def parse_steps(raw: List[Dict[str, Any]]) -> List[Any]:
    """Validate a recipe's ``steps``; :class:`StepError` names the first bad one."""
    if len(raw) > MAX_STEPS:
        raise EngineError(f"At most {MAX_STEPS} steps")
    try:
        return _steps_adapter.validate_python(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = first.get("loc", ())
        index = loc[0] if loc and isinstance(loc[0], int) else 0
        where = ".".join(str(p) for p in loc[2:] if not isinstance(p, int))
        message = first.get("msg", "invalid step")
        raise StepError(index, f"{where}: {message}" if where else message) from None


Schema = List[Tuple[str, str]]  # (name, DuckDB type), in order


@dataclass
class Compiled:
    sql: str
    params: List[Any]
    schema: Schema
    # The CTE of each step, for its row count.
    stages: List[str] = field(default_factory=list)
    ctes: str = ""
    # The table's schema after each step.
    step_schemas: List[Schema] = field(default_factory=list)


def _need(index: int, schema: Schema, column: str) -> str:
    names = [n for n, _ in schema]
    if column not in names:
        raise StepError(index, f"unknown column '{column}'")
    return column


def _type_of(schema: Schema, column: str) -> str:
    return dict(schema)[column]


def _cols(schema: Schema) -> List[str]:
    return [n for n, _ in schema]


_SCALAR = re.compile(r"^[A-Z ]+(\(\d+(,\s*\d+)?\))?$")


def _scalar_type(kind: str) -> Optional[str]:
    """``kind`` when it is a plain scalar type (``BIGINT``, ``DECIMAL(18,3)``);
    None for a nested one, whose text may carry a file's field names."""
    return kind if _SCALAR.match(kind) else None


def _is_text(kind: str) -> bool:
    return kind.upper().startswith("VARCHAR")


def compile_steps(steps: List[Any], schema: Schema, source: str = "source") -> Compiled:
    """``(sql, params, output schema)`` of ``steps`` over table ``source``."""
    params: List[Any] = []
    ctes: List[str] = [
        f"s0 AS (SELECT *, row_number() OVER () AS {quote_ident(ROW)} FROM {quote_ident(source)})"
    ]
    current = list(schema)
    stages: List[str] = []
    step_schemas: List[Schema] = []
    for i, step in enumerate(steps):
        prev, name = f"s{i}", f"s{i + 1}"
        row = quote_ident(ROW)
        if isinstance(step, Select):
            seen = set()
            for col in step.columns:
                _need(i, current, col)
                if col in seen:
                    raise StepError(i, f"column '{col}' is selected twice")
                seen.add(col)
            body = ", ".join(quote_ident(c) for c in step.columns)
            ctes.append(f"{name} AS (SELECT {body}, {row} FROM {prev})")
            current = [(c, _type_of(current, c)) for c in step.columns]
        elif isinstance(step, Rename):
            for old, new in step.mapping.items():
                _need(i, current, old)
                if not new.strip() or new == ROW:
                    raise StepError(i, f"'{new}' is not a usable column name")
            renamed = [(step.mapping.get(n, n), t) for n, t in current]
            names = [n for n, _ in renamed]
            if len({n.lower() for n in names}) != len(names):
                raise StepError(i, "two columns would have the same name")
            body = ", ".join(
                f"{quote_ident(n)} AS {quote_ident(step.mapping.get(n, n))}"
                for n, _ in current
            )
            ctes.append(f"{name} AS (SELECT {body}, {row} FROM {prev})")
            current = renamed
        elif isinstance(step, Cast):
            col = _need(i, current, step.column)
            target = _SQL_TYPES[step.to]
            value = f"CAST({quote_ident(col)} AS VARCHAR)"
            if step.decimal_comma and step.to in ("integer", "double"):
                value = (
                    f"replace(regexp_replace({value}, '[\\s  ]', '', 'g'), ',', '.')"
                )
            if step.format and step.to in ("date", "timestamp"):
                fn = "strptime" if step.on_error == "fail" else "try_strptime"
                params.append(step.format)
                expr = f"CAST({fn}({value}, ?) AS {target})"
            else:
                fn = "CAST" if step.on_error == "fail" else "TRY_CAST"
                expr = f"{fn}(NULLIF(TRIM({value}), '') AS {target})"
            body = ", ".join(
                f"{expr} AS {quote_ident(n)}" if n == col else quote_ident(n)
                for n in _cols(current)
            )
            ctes.append(f"{name} AS (SELECT {body}, {row} FROM {prev})")
            current = [(n, target if n == col else t) for n, t in current]
        elif isinstance(step, Filter):
            col = quote_ident(_need(i, current, step.column))
            op = step.operator
            if op in ("is_null", "not_null"):
                where = f"{col} IS {'' if op == 'is_null' else 'NOT '}NULL"
            elif op in ("in", "not_in"):
                if not isinstance(step.value, list) or not step.value:
                    raise StepError(i, "value: a non-empty list is expected")
                params.append([str(v) for v in step.value])
                where = f"{'NOT ' if op == 'not_in' else ''}list_contains(?, CAST({col} AS VARCHAR))"
            elif op == "contains":
                if step.value is None:
                    raise StepError(i, "value: some text is expected")
                params.append(str(step.value))
                where = f"contains(CAST({col} AS VARCHAR), ?)"
            else:
                if step.value is None or isinstance(step.value, (list, dict)):
                    raise StepError(i, "value: a single value is expected")
                symbol = {
                    "eq": "=",
                    "ne": "<>",
                    "lt": "<",
                    "le": "<=",
                    "gt": ">",
                    "ge": ">=",
                }[op]
                params.append(step.value)
                kind = _scalar_type(_type_of(current, step.column))
                if kind is None:  # a nested type: compared as text
                    where = f"CAST({col} AS VARCHAR) {symbol} CAST(? AS VARCHAR)"
                else:
                    where = f"{col} {symbol} CAST(? AS {kind})"
            ctes.append(f"{name} AS (SELECT * FROM {prev} WHERE {where})")
        elif isinstance(step, Dedup):
            for c in step.columns:
                _need(i, current, c)
            keys = step.columns or _cols(current)
            partition = ", ".join(quote_ident(c) for c in keys)
            order = f"{row} {'ASC' if step.keep == 'first' else 'DESC'}"
            ctes.append(
                f"{name} AS (SELECT * FROM {prev} QUALIFY row_number() OVER "
                f"(PARTITION BY {partition} ORDER BY {order}) = 1)"
            )
        elif isinstance(step, Mask):
            col = _need(i, current, step.column)
            if step.method == "drop":
                kept = [(n, t) for n, t in current if n != col]
                if not kept:
                    raise StepError(i, "the last column can't be dropped")
                body = ", ".join(quote_ident(n) for n, _ in kept)
                current = kept
            else:
                text = f"CAST({quote_ident(col)} AS VARCHAR)"
                if step.method == "hash":
                    expr = f"sha256({text})"
                elif step.method == "redact":
                    expr = (
                        f"CASE WHEN {quote_ident(col)} IS NULL THEN NULL ELSE '***' END"
                    )
                else:
                    params.append(step.keep)
                    expr = f"left({text}, ?)"
                body = ", ".join(
                    f"{expr} AS {quote_ident(n)}" if n == col else quote_ident(n)
                    for n in _cols(current)
                )
                current = [(n, "VARCHAR" if n == col else t) for n, t in current]
            ctes.append(f"{name} AS (SELECT {body}, {row} FROM {prev})")
        elif isinstance(step, Trim):
            for c in step.columns:
                _need(i, current, c)
            targets = set(step.columns or [n for n, t in current if _is_text(t)])
            body = ", ".join(
                f"trim({quote_ident(n)}) AS {quote_ident(n)}"
                if n in targets and _is_text(t)
                else quote_ident(n)
                for n, t in current
            )
            ctes.append(f"{name} AS (SELECT {body}, {row} FROM {prev})")
        elif isinstance(step, Limit):
            params.append(step.rows)
            ctes.append(f"{name} AS (SELECT * FROM {prev} ORDER BY {row} LIMIT ?)")
        else:  # pragma: no cover — the union is closed
            raise StepError(i, "unknown step")
        stages.append(name)
        step_schemas.append(list(current))
    last = f"s{len(steps)}"
    columns = ", ".join(quote_ident(n) for n, _ in current)
    with_clause = "WITH " + ", ".join(ctes)
    sql = f"{with_clause} SELECT {columns} FROM {last} ORDER BY {quote_ident(ROW)}"
    return Compiled(
        sql=sql,
        params=params,
        schema=current,
        stages=stages,
        ctes=with_clause,
        step_schemas=step_schemas,
    )


def table_schema(session: EngineSession, table: str) -> Schema:
    return [
        (r[0], r[1])
        for r in session.fetchall(
            f"SELECT column_name, column_type FROM (DESCRIBE {quote_ident(table)})"
        )
    ]


@dataclass
class Applied:
    schema: Schema
    step_rows: List[int]
    rows: int
    step_schemas: List[Schema] = field(default_factory=list)


def _step_counts(session: EngineSession, compiled: Compiled) -> List[int]:
    if not compiled.stages:
        return []
    counts = ", ".join(f"(SELECT count(*) FROM {stage})" for stage in compiled.stages)
    row = session.fetchone(f"{compiled.ctes} SELECT {counts}", compiled.params)
    return [int(v) for v in row] if row else []


def apply_steps(
    session: EngineSession,
    raw_steps: List[Dict[str, Any]],
    *,
    source: str = "source",
    target: str = "result",
) -> Applied:
    """Run ``raw_steps`` over ``source`` into the table ``target``."""
    import duckdb

    steps = parse_steps(raw_steps)
    compiled = compile_steps(steps, table_schema(session, source), source)
    try:
        session.execute(
            f"CREATE OR REPLACE TABLE {quote_ident(target)} AS {compiled.sql}",
            compiled.params,
        )
        counts = _step_counts(session, compiled)
    except duckdb.ConversionException as exc:
        raise EngineError("A cast failed: " + str(exc).splitlines()[0][:200]) from None
    except duckdb.Error as exc:
        raise EngineError(
            "The steps can't run: " + str(exc).splitlines()[0][:200]
        ) from None
    total = session.fetchone(f"SELECT count(*) FROM {quote_ident(target)}")
    return Applied(
        schema=compiled.schema,
        step_rows=counts,
        rows=int(total[0]) if total else 0,
        step_schemas=compiled.step_schemas,
    )
