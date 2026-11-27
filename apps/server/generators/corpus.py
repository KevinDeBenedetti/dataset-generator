"""Corpus documents from rows (#317): each row — or each chunk of a long
row — becomes ``{id, title, text, metadata}`` for retrieval.

``text_template`` and ``title_template`` use the facts syntax
(generators/facts.py); ``metadata_columns`` are kept as typed fields of a
``metadata`` struct, which a vector collection's payload carries and its search
filters on (``metadata.<column>``). ``chunk_chars`` cuts a long text at
paragraph, then sentence, then word boundaries.
"""

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from pydantic import BaseModel, Field, field_validator

from server.generators.facts import TemplateError, _parse, placeholders, render

MAX_DOCS = 1_000_000


class CorpusOptions(BaseModel):
    text_template: str = Field(..., min_length=1, max_length=4000)
    title_template: Optional[str] = Field(None, max_length=1000)
    metadata_columns: List[str] = Field(default_factory=list, max_length=50)
    # The column naming a row (its documents' ids); else its position.
    id_column: Optional[str] = Field(None, max_length=200)
    chunk_chars: Optional[int] = Field(None, ge=200, le=20_000)
    max_docs: int = Field(100_000, ge=1, le=MAX_DOCS)

    @field_validator("text_template", "title_template")
    @classmethod
    def _parses(cls, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        try:
            _parse(text)
        except TemplateError as exc:
            raise ValueError(str(exc)) from None
        return text


def check_columns(options: CorpusOptions, columns: Iterable[str]) -> None:
    known = set(columns)
    names = placeholders(options.text_template) + placeholders(
        options.title_template or ""
    )
    names += list(options.metadata_columns)
    if options.id_column:
        names.append(options.id_column)
    missing = [n for n in names if n not in known]
    if missing:
        raise TemplateError(f"no column '{missing[0]}'")


def chunks(text: str, size: Optional[int]) -> List[str]:
    """``text`` in pieces of at most ``size`` characters (whole when None)."""
    if not size or len(text) <= size:
        return [text] if text else []
    out: List[str] = []
    current = ""
    pieces = re.split(r"(\n\s*\n|(?<=[.!?])\s+|\s+)", text)
    for piece in pieces:
        if len(current) + len(piece) > size and current.strip():
            out.append(current.strip())
            current = ""
        while len(piece) > size:  # a single word longer than a chunk
            out.append(piece[:size])
            piece = piece[size:]
        current += piece
    if current.strip():
        out.append(current.strip())
    return out


def documents(
    options: CorpusOptions, rows: Iterable[Dict[str, Any]]
) -> Iterator[Dict[str, Any]]:
    made = 0
    for n, row in enumerate(rows):
        key = str(row.get(options.id_column)) if options.id_column else str(n + 1)
        text = render(options.text_template, row) if options.text_template else ""
        title = render(options.title_template, row) if options.title_template else ""
        metadata = {c: row.get(c) for c in options.metadata_columns}
        parts = chunks(text, options.chunk_chars)
        for i, part in enumerate(parts):
            doc: Dict[str, Any] = {
                "id": key if len(parts) == 1 else f"{key}-{i + 1}",
                "title": title,
                "text": part,
            }
            # Parquet has no empty struct: no metadata column without fields.
            if metadata:
                doc["metadata"] = metadata
            yield doc
            made += 1
            if made >= options.max_docs:
                return


def write_documents(path: Path, docs: Iterable[Dict[str, Any]]) -> int:
    """The documents as ZSTD Parquet at ``path``; how many."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = list(docs)
    if not rows:
        raise TemplateError("No document: every row's text is empty")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")
    return len(rows)
