"""Q&A pairs from rows, with no model: templates over the columns (a **Fact**,
GLOSSARY.md), rebuilt on every run.

A template is ``{question, answer, condition?, category?}``. Placeholders are
``{column}`` or ``{column|filter}``; ``{{`` and ``}}`` are literal braces.
Nothing else is interpreted — no attribute, no call, no loop — so a template
can only ever print a row's values. Filters: ``number`` (French grouping,
``1 284``), ``decimal`` (``1 284,5``), ``date_fr`` (``2 janvier 2026``),
``lower``, ``upper``, ``title``. A rendered field is cut at ``MAX_FIELD``
characters.
"""

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_TEMPLATE = 1000
MAX_FIELD = 4000
MAX_TEMPLATES = 20
NBSP = " "
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}|]{1,200})(?:\|([a-z_]{1,20}))?\}|[{}]")
FILTERS = ("number", "decimal", "date_fr", "lower", "upper", "title")


class TemplateError(ValueError):
    """A template that can't be used: the message says where."""


def _parse(text: str) -> List[Any]:
    """``text`` as literal strings and ``(column, filter)`` placeholders."""
    parts: List[Any] = []
    pos = 0
    for match in _TOKEN.finditer(text):
        if match.start() > pos:
            parts.append(text[pos : match.start()])
        brace = match.group(0)
        if brace == "{{":
            parts.append("{")
        elif brace == "}}":
            parts.append("}")
        elif match.group(1) is None:
            raise TemplateError(f"a lone '{brace}' (write '{brace * 2}' for a brace)")
        else:
            column, flt = match.group(1).strip(), match.group(2)
            if flt is not None and flt not in FILTERS:
                raise TemplateError(
                    f"unknown filter '{flt}' (one of {', '.join(FILTERS)})"
                )
            parts.append((column, flt))
        pos = match.end()
    if pos < len(text):
        parts.append(text[pos:])
    return parts


def placeholders(text: str) -> List[str]:
    return [p[0] for p in _parse(text) if isinstance(p, tuple)]


def _group(n: int) -> str:
    sign = "-" if n < 0 else ""
    digits = f"{abs(n)}"
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return sign + NBSP.join(groups)


def _number(value: Any, decimals: bool) -> str:
    try:
        number = float(value) if not isinstance(value, (int, Decimal)) else value
    except (TypeError, ValueError):
        return str(value)
    if not decimals or float(number) == int(float(number)):
        return _group(int(round(float(number))))
    whole, frac = f"{abs(float(number)):.2f}".rstrip("0").rstrip(".").split(".")
    text = _group(int(whole)) + "," + frac
    return ("-" if float(number) < 0 else "") + text


def _date_fr(value: Any) -> str:
    when: Optional[date] = None
    if isinstance(value, datetime):
        when = value.date()
    elif isinstance(value, date):
        when = value
    else:
        try:
            when = date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    day = "1er" if when.day == 1 else str(when.day)
    return f"{day} {_MONTHS[when.month - 1]} {when.year}"


def _apply(value: Any, flt: Optional[str]) -> str:
    if value is None:
        return ""
    if flt == "number":
        return _number(value, decimals=False)
    if flt == "decimal":
        return _number(value, decimals=True)
    if flt == "date_fr":
        return _date_fr(value)
    text = value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if flt == "lower":
        return text.lower()
    if flt == "upper":
        return text.upper()
    if flt == "title":
        return text.title()
    return text


def render(text: str, row: Dict[str, Any]) -> str:
    out: List[str] = []
    for part in _parse(text):
        if isinstance(part, tuple):
            column, flt = part
            if column not in row:
                raise TemplateError(f"no column '{column}'")
            out.append(_apply(row[column], flt))
        else:
            out.append(part)
    rendered = "".join(out).strip()
    return rendered if len(rendered) <= MAX_FIELD else rendered[: MAX_FIELD - 1] + "…"


class Condition(BaseModel):
    column: str = Field(..., max_length=200)
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


class FactTemplate(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_TEMPLATE)
    answer: str = Field(..., min_length=1, max_length=MAX_TEMPLATE)
    condition: Optional[Condition] = None
    category: Optional[str] = Field(None, max_length=100)

    @field_validator("question", "answer")
    @classmethod
    def _parses(cls, text: str) -> str:
        try:
            _parse(text)
        except TemplateError as exc:
            raise ValueError(str(exc)) from None
        return text


class FactsOptions(BaseModel):
    generator: Literal["facts"] = "facts"
    templates: List[FactTemplate] = Field(..., min_length=1, max_length=MAX_TEMPLATES)
    max_pairs: int = Field(10_000, ge=1, le=200_000)
    # A column naming the row (a commune code): the pairs' source and ids.
    key_column: Optional[str] = Field(None, max_length=200)
    language: str = Field("fr", max_length=10)


def _compare(value: Any, operator: str, expected: Any) -> bool:
    if operator == "is_null":
        return value is None or value == ""
    if operator == "not_null":
        return value is not None and value != ""
    if value is None:
        return False
    if operator in ("in", "not_in"):
        members = {str(v) for v in (expected or [])}
        return (str(value) in members) == (operator == "in")
    if operator == "contains":
        return str(expected).lower() in str(value).lower()
    try:
        return _ordered(float(value), operator, float(expected))
    except (TypeError, ValueError):
        return _ordered(str(value), operator, str(expected))


def _ordered(left: Any, operator: str, right: Any) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "lt":
        return left < right
    if operator == "le":
        return left <= right
    if operator == "gt":
        return left > right
    return left >= right


def check_columns(options: FactsOptions, columns: Iterable[str]) -> None:
    """Every placeholder and condition names a column of the table."""
    known = set(columns)
    for i, template in enumerate(options.templates, 1):
        names = placeholders(template.question) + placeholders(template.answer)
        if template.condition:
            names.append(template.condition.column)
        if options.key_column:
            names.append(options.key_column)
        missing = [n for n in names if n not in known]
        if missing:
            raise TemplateError(f"Template {i}: no column '{missing[0]}'")


def facts(
    options: FactsOptions,
    rows: Iterable[Dict[str, Any]],
    *,
    source: str,
    recipe_id: str,
    created_at: str,
) -> List[Dict[str, Any]]:
    """The pairs of ``rows`` (in the Q&A draft schema), ``max_pairs`` at most."""
    pairs: List[Dict[str, Any]] = []
    for n, row in enumerate(rows):
        key = str(row.get(options.key_column)) if options.key_column else str(n + 1)
        for i, template in enumerate(options.templates):
            c = template.condition
            if c and not _compare(row.get(c.column), c.operator, c.value):
                continue
            question = render(template.question, row)
            answer = render(template.answer, row)
            if not question or not answer:
                continue
            identity = (
                f"{recipe_id}|{i}|{key}"
                if options.key_column
                else f"{question}\n{answer}"
            )
            pairs.append(
                {
                    "id": hashlib.sha256(identity.encode()).hexdigest()[:16],
                    "question": question,
                    "answer": answer,
                    "context": json.dumps(row, ensure_ascii=False, default=str)[
                        :MAX_FIELD
                    ],
                    "source_url": f"{source}#{key}" if source else key,
                    "confidence": 1.0,
                    "created_at": created_at,
                    "category": template.category or "fact",
                }
            )
            if len(pairs) >= options.max_pairs:
                return pairs
    return pairs
