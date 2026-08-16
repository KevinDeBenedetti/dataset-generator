"""Pure, in-memory duplicate detection for QA pairs.

The comparison logic lives here, free of any database or ORM dependency, so it
can be unit-tested directly and reused as the QA storage layer evolves.
``server.services.qa.QAService`` loads the target dataset's existing Langfuse
items into :class:`QAEntry` values once per pipeline run and delegates every
comparison to :func:`classify_duplicate` against that in-memory pool — no
network call is repeated per QA pair.

Semantics:

* **exact** — a candidate whose content hash already exists (anywhere in the
  pool) is an exact duplicate; this always wins over a similarity match.
* **similar** — otherwise, a candidate is a similar duplicate of the first
  existing entry with the *same source URL* whose question similarity clears
  the caller's ``threshold`` **and** whose context similarity clears
  :data:`CONTEXT_SIMILARITY_FLOOR`.
* **new** — anything else.
"""

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Literal, Optional, Tuple

# A candidate counts as a similar duplicate only when BOTH the question clears
# the caller's threshold AND the context is near-identical. The context floor
# guards against collapsing identically-worded questions that were asked over
# genuinely different passages.
CONTEXT_SIMILARITY_FLOOR = 0.95

DuplicateType = Literal["exact", "similar", "new"]


@dataclass(frozen=True)
class QAEntry:
    """Minimal view of a QA pair used for duplicate detection."""

    hash: str
    question: str
    context: str
    source_url: str


@dataclass(frozen=True)
class DuplicateVerdict:
    """Outcome of classifying a candidate against a set of existing entries."""

    type: DuplicateType
    duplicate_hash: Optional[str]
    similarity_score: float


def compute_hash_from_content(
    question: str, answer: str, context: str, source_url: str = ""
) -> str:
    """Content-hash id for a QA pair — stable across re-runs (idempotent sync)."""
    question_normalized = " ".join(question.strip().split())
    context_normalized = " ".join(context.strip().split())
    content = f"{question_normalized}|{context_normalized}|{source_url}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def find_similar(
    candidate: QAEntry,
    existing: Iterable[QAEntry],
    threshold: float = 0.9,
) -> Optional[Tuple[str, float]]:
    """Return ``(hash, question_similarity)`` of the first same-source entry that
    is a near-match of ``candidate``, or ``None``.

    A near-match needs the question similarity to reach ``threshold`` and the
    context similarity to reach :data:`CONTEXT_SIMILARITY_FLOOR`.
    """
    for entry in existing:
        if entry.source_url != candidate.source_url:
            continue
        question_similarity = _ratio(candidate.question, entry.question)
        context_similarity = _ratio(candidate.context, entry.context)
        if (
            question_similarity >= threshold
            and context_similarity >= CONTEXT_SIMILARITY_FLOOR
        ):
            return entry.hash, question_similarity
    return None


def classify_duplicate(
    candidate: QAEntry,
    existing: Iterable[QAEntry],
    similarity_threshold: float = 0.9,
) -> DuplicateVerdict:
    """Classify ``candidate`` against ``existing`` as exact / similar / new.

    Exact wins over similar: an identical content hash anywhere is an exact
    duplicate; otherwise a same-source near-match (see :func:`find_similar`) is
    a similar duplicate.
    """
    entries: List[QAEntry] = list(existing)

    for entry in entries:
        if entry.hash == candidate.hash:
            return DuplicateVerdict("exact", entry.hash, 1.0)

    match = find_similar(candidate, entries, similarity_threshold)
    if match is not None:
        return DuplicateVerdict("similar", match[0], match[1])

    return DuplicateVerdict("new", None, 0.0)
