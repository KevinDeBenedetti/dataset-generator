"""Local sentence embeddings for QA generation — no API call, no GPU.

Backs four checks shared by the in-app pipeline (``services/qa.py``) and the
scheduled Q&A job (``jobs/qa_dataset.py``):

* **semantic dedup** — a new question whose cosine to an existing one reaches
  the threshold is a rephrasing, not a new pair;
* **targeted prompts** — the existing questions nearest a source are fed back
  to the LLM as "do not ask these again";
* **uncovered topics** — source sections no question is close to are the
  topics to ask about next;
* **answer grounding** — an answer far from every chunk of its source is a
  hallucination signal, flagged for review.

The model runs through FastEmbed (ONNX Runtime, no torch), downloaded from the
Hugging Face Hub on first use and cached under ``FASTEMBED_CACHE_PATH``.
Everything here except :func:`get_local_embedder` is pure and takes an
:class:`Embedder` or plain vectors, so tests inject a fake and never download a
model. Vectors are L2-normalised on the way out: cosine is a dot product.
"""

import logging
import re
import threading
import time
from typing import List, Optional, Protocol, Sequence, Tuple

import numpy as np

from server.core.config import config

logger = logging.getLogger(__name__)

# The MiniLM models truncate input at 128 word pieces (~500 characters of
# prose), so longer sections are split before embedding rather than silently
# cut — the tail of a long section would otherwise never count.
SECTION_MAX_CHARS = 500
# Shorter fragments (a lone heading, a badge line) carry no topic of their own.
SECTION_MIN_CHARS = 40

# A failed model load (no network, full disk) is not retried on every call:
# FastEmbed itself retries with backoff for ~40 s per attempt.
_RETRY_AFTER_FAILURE_S = 600

_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)


class Embedder(Protocol):
    """Anything that turns texts into an ``(n, dim)`` array of unit vectors."""

    model_name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation; zero rows stay zero instead of turning NaN."""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


class LocalEmbedder:
    """FastEmbed ``TextEmbedding`` behind the :class:`Embedder` protocol."""

    def __init__(self, model_name: str, cache_dir: Optional[str] = None):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return normalize(np.array(list(self._model.embed(list(texts)))))


_lock = threading.Lock()
_embedder: Optional[LocalEmbedder] = None
_failed_at: Optional[float] = None


def get_local_embedder() -> Optional[Embedder]:
    """The process-wide embedder, or ``None`` when disabled or unloadable.

    ``None`` is the signal for callers to fall back to their lexical path —
    embeddings improve generation, they must never be what makes it fail.
    Loads eagerly (so a broken model surfaces here, not mid-run) and at most
    once; a failed load is retried only after ``_RETRY_AFTER_FAILURE_S``.
    """
    global _embedder, _failed_at
    if not config.semantic_enabled:
        return None
    with _lock:
        if _embedder is not None:
            return _embedder
        if _failed_at is not None and time.monotonic() - _failed_at < (
            _RETRY_AFTER_FAILURE_S
        ):
            return None
        try:
            _embedder = LocalEmbedder(
                config.semantic_model, config.fastembed_cache_path or None
            )
            logger.info("Loaded embedding model %s", config.semantic_model)
            return _embedder
        except Exception as exc:  # noqa: BLE001 — degrade to lexical, never fail
            _failed_at = time.monotonic()
            logger.warning(
                "Embedding model %s unavailable, falling back to lexical checks: %s",
                config.semantic_model,
                exc,
            )
            return None


class SemanticIndex:
    """Texts and their unit vectors, searchable by cosine — in memory.

    Sized for one dataset (hundreds to a few thousand questions): a brute-force
    matrix product is exact and faster than any ANN index at that scale.
    """

    def __init__(self) -> None:
        self.texts: List[str] = []
        self._matrix: Optional[np.ndarray] = None

    def __len__(self) -> int:
        return len(self.texts)

    def add(self, texts: Sequence[str], vectors: np.ndarray) -> None:
        if not texts:
            return
        vectors = normalize(vectors)
        if len(vectors) != len(texts):
            raise ValueError(f"{len(vectors)} vectors for {len(texts)} texts")
        self.texts.extend(texts)
        self._matrix = (
            vectors if self._matrix is None else np.vstack([self._matrix, vectors])
        )

    def scores(self, vectors: np.ndarray) -> np.ndarray:
        """Per indexed text, its cosine to ``vectors`` (empty if none indexed).

        ``vectors`` is one vector or several (e.g. one per section of a long
        source); with several, each text scores its best match among them.
        """
        if self._matrix is None or not len(vectors):
            return np.zeros(0, dtype=np.float32)
        return (self._matrix @ normalize(vectors).T).max(axis=1)

    def best(self, vector: np.ndarray) -> Optional[Tuple[int, float]]:
        """``(index, cosine)`` of the closest text, or ``None`` when empty."""
        scores = self.scores(vector)
        if not len(scores):
            return None
        i = int(np.argmax(scores))
        return i, float(scores[i])

    def top_k(self, vector: np.ndarray, k: int) -> List[Tuple[int, float]]:
        """The ``k`` closest ``(index, cosine)``, most similar first."""
        scores = self.scores(vector)
        order = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in order]


def find_semantic_duplicate(
    vector: np.ndarray, index: SemanticIndex, threshold: float
) -> Optional[Tuple[int, float]]:
    """``(index, cosine)`` of an indexed text at or above ``threshold``, else None."""
    match = index.best(vector)
    if match is not None and match[1] >= threshold:
        return match
    return None


def nearest_texts(
    vectors: np.ndarray, index: SemanticIndex, k: int = 15, floor: float = 0.0
) -> List[str]:
    """The ``k`` indexed texts closest to ``vectors`` — the "don't repeat" list.

    Texts under ``floor`` are left out: for a brand-new source the nearest
    questions are about something else and only add noise to a prompt.
    """
    return [index.texts[i] for i, s in index.top_k(vectors, k) if s >= floor]


def split_sections(
    text: str,
    max_chars: int = SECTION_MAX_CHARS,
    min_chars: int = SECTION_MIN_CHARS,
) -> List[str]:
    """Split markdown into heading sections, then paragraphs up to ``max_chars``.

    Each piece fits the model's input window, so the embedding covers all of
    it. Pieces under ``min_chars`` are dropped; a paragraph longer than
    ``max_chars`` on its own is hard-cut rather than lost.
    """
    bounds = sorted({0, len(text), *(m.start() for m in _HEADING.finditer(text))})
    sections = [text[a:b] for a, b in zip(bounds, bounds[1:])]

    pieces: List[str] = []
    for section in sections:
        current = ""
        for paragraph in re.split(r"\n\s*\n", section):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            while len(paragraph) > max_chars:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(paragraph[:max_chars])
                paragraph = paragraph[max_chars:]
            if current and len(current) + len(paragraph) + 2 > max_chars:
                pieces.append(current)
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}" if current else paragraph
        if current:
            pieces.append(current)
    return [p for p in pieces if len(p) >= min_chars]


def uncovered_sections(
    sections: Sequence[str],
    section_vectors: np.ndarray,
    questions: SemanticIndex,
    threshold: float,
) -> List[str]:
    """Sections whose closest question stays under ``threshold`` (all, if none)."""
    if not len(questions):
        return list(sections)
    out: List[str] = []
    for section, vector in zip(sections, section_vectors):
        match = questions.best(vector)
        if match is None or match[1] < threshold:
            out.append(section)
    return out


def grounding_scores(
    answer_vectors: np.ndarray, chunk_vectors: np.ndarray
) -> np.ndarray:
    """Per answer, the cosine to its closest source chunk (0 when no chunks)."""
    answers = normalize(answer_vectors)
    if not len(chunk_vectors):
        return np.zeros(len(answers), dtype=np.float32)
    return (answers @ normalize(chunk_vectors).T).max(axis=1)
