"""Embeddings, on the endpoint: one model, OPENAI_EMBEDDING_MODEL.

The model is served by the caller's OpenAI-compatible endpoint
(:class:`EndpointEmbedder`, named ``openai:<id>``). It backs four checks shared
by the in-app pipeline (``services/qa.py``) and the GitHub Q&A jobs
(``jobs/qa_dataset.py``):

* **semantic dedup** — a new question whose cosine to an existing one reaches
  the threshold is a rephrasing, not a new pair;
* **targeted prompts** — the existing questions nearest a source are fed back
  to the LLM as "do not ask these again";
* **uncovered topics** — source sections no question is close to are the
  topics to ask about next;
* **answer grounding** — an answer far from every chunk of its source is a
  hallucination signal, flagged for review.

Without it — no model set, no endpoint, or one that doesn't answer —
:func:`get_embedder` returns ``None`` and the checks take their lexical path.
A vector collection (``services/collections.py``) is built with one of the
endpoint's embedding models (:func:`collection_models`). Everything else here
is pure and takes an :class:`Embedder` or plain vectors, so tests inject a fake.
Vectors are L2-normalised on the way out: cosine is a dot product.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, cast

import numpy as np

from server.core.config import config
from server.services.credentials import Credentials
from server.services.providers import get_provider
from server.services.providers.openai import OpenAIProvider, connection_key

logger = logging.getLogger(__name__)

# Long sections are split before embedding, so a vector stands for one topic
# and nothing past a model's input window is silently cut.
SECTION_MAX_CHARS = 500
# Shorter fragments (a lone heading, a badge line) carry no topic of their own.
SECTION_MIN_CHARS = 40

# A failed probe is retried after this long, not on every call.
_RETRY_AFTER_FAILURE_S = 600

_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)

# A model named "openai:<id>" is served by the OpenAI-compatible endpoint.
ENDPOINT_PREFIX = "openai:"


class Embedder(Protocol):
    """Anything that turns texts into an ``(n, dim)`` array of unit vectors."""

    model_name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class RetrievalEmbedder(Protocol):
    """What a vector collection is built and searched with."""

    model_name: str

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class EmbeddingModelError(RuntimeError):
    """The endpoint can't embed with the model (its message is safe to show)."""


def normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation; zero rows stay zero instead of turning NaN."""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def is_endpoint_model(name: str) -> bool:
    return name.startswith(ENDPOINT_PREFIX)


def _openai() -> OpenAIProvider:
    # The registry's instance: its discovery cache lists the endpoint's models.
    return cast(OpenAIProvider, get_provider("openai"))


def _endpoint_configured(creds: Optional[Credentials]) -> bool:
    return creds is not None and _openai().configured(creds)


@dataclass(frozen=True)
class Thresholds:
    """Where each check draws its line, on its embedding model's cosine scale:
    a question at or above ``dedup`` of an existing one is a rephrasing, an
    answer below ``grounding`` of its source is held for review, a section
    below ``uncovered`` of every question is one to ask about."""

    dedup: float
    grounding: float
    uncovered: float


def default_thresholds() -> Thresholds:
    """The defaults, measured on a small local model the server no longer runs
    (core/config.py): an endpoint model is measured on the Models page."""
    return Thresholds(
        config.semantic_dedup_threshold,
        config.answer_grounding_threshold,
        config.uncovered_section_threshold,
    )


def thresholds_of(embedder: Any) -> Thresholds:
    """The thresholds an embedder's checks use (a test's fake: the defaults)."""
    return getattr(embedder, "thresholds", None) or default_thresholds()


class EndpointEmbedder:
    """An embedding model of the caller's OpenAI-compatible endpoint.

    Blocking: callers run it in a thread. A failed call raises
    :class:`EmbeddingModelError`.
    """

    def __init__(
        self,
        model_id: str,
        creds: Credentials,
        thresholds: Optional[Thresholds] = None,
    ):
        self.model_id = model_id
        self.model_name = ENDPOINT_PREFIX + model_id
        self.creds = creds
        self.thresholds = thresholds or default_thresholds()

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        try:
            vectors = _openai().embed(self.model_id, texts, self.creds)
        except Exception as exc:  # noqa: BLE001 — ProviderError, or a bad endpoint URL
            raise EmbeddingModelError(
                f"The endpoint could not embed with {self.model_id}: {exc}"
            ) from None
        return normalize(np.array(vectors, dtype=np.float32))

    # The OpenAI API has no query/passage distinction.
    embed_passages = embed
    embed_queries = embed


# Probe outcomes per endpoint, key and model (hashed): a success is trusted
# for _PROBE_OK_S, a failure retried after _RETRY_AFTER_FAILURE_S.
_PROBE_OK_S = 300
_probe_lock = threading.Lock()
_probed: Dict[str, Tuple[bool, float]] = {}


def _answers(embedder: EndpointEmbedder) -> bool:
    """Whether the endpoint embeds with this model now (one short call)."""
    key = f"{connection_key(embedder.creds)}|{embedder.model_id}"
    now = time.monotonic()
    with _probe_lock:
        known = _probed.get(key)
    if known is not None:
        ok, at = known
        if now - at < (_PROBE_OK_S if ok else _RETRY_AFTER_FAILURE_S):
            return ok
    try:
        embedder.embed(["ping"])
        ok = True
    except EmbeddingModelError as exc:
        ok = False
        logger.warning("%s, the checks compare the text instead", exc)
    with _probe_lock:
        _probed[key] = (ok, time.monotonic())
    return ok


@dataclass(frozen=True)
class EmbeddingChoice:
    """The model a user's checks embed with, and where its checks draw lines."""

    model_id: str  # '' = none
    thresholds: Thresholds
    measured: bool  # measured for this model on the built-in set


def embedding_choice(creds: Optional[Credentials]) -> EmbeddingChoice:
    """For ``creds``' user: the embedding model chosen on the Models page,
    else OPENAI_EMBEDDING_MODEL; with the thresholds measured for it there,
    else the defaults. Never raises: a database failure leaves the defaults,
    the checks run anyway."""
    model_id = config.openai_embedding_model
    thresholds, measured = default_thresholds(), False
    user_id = creds.user_id if creds is not None else ""
    if user_id:
        try:
            from server.services.calibration import load_choice

            chosen, calibrated = load_choice(user_id, model_id)
        except Exception as exc:  # noqa: BLE001 — degrade to the env's model
            logger.warning("Could not read the embedding choice, using env: %s", exc)
        else:
            model_id = chosen or model_id
            if calibrated is not None:
                thresholds, measured = calibrated, True
    return EmbeddingChoice(model_id, thresholds, measured)


def default_embedding_model(creds: Optional[Credentials]) -> str:
    """``openai:<model>`` the checks embed with for ``creds``, with an endpoint,
    else "" (unprobed: the checks compare the text when the endpoint can't embed)."""
    model_id = embedding_choice(creds).model_id
    if model_id and _endpoint_configured(creds):
        return ENDPOINT_PREFIX + model_id
    return ""


def get_embedder(creds: Optional[Credentials] = None) -> Optional[Embedder]:
    """The embedder of the duplicate, grounding and coverage checks for
    ``creds``: their user's embedding model (or OPENAI_EMBEDDING_MODEL) on
    their endpoint when it answers, with its thresholds — else ``None``, the
    lexical path. Blocking (a database read, a probe): call it in a thread."""
    choice = embedding_choice(creds)
    if not choice.model_id or not _endpoint_configured(creds):
        return None
    embedder = EndpointEmbedder(
        choice.model_id, cast(Credentials, creds), choice.thresholds
    )
    return embedder if _answers(embedder) else None


# --- Collection models (services/collections.py) --------------------------------


@dataclass(frozen=True)
class EmbeddingModel:
    """A model a vector collection can be embedded with, served by the
    caller's OpenAI-compatible endpoint (named ``openai:<id>``)."""

    name: str
    description: str
    provider: str = "openai"


def collection_models(creds: Optional[Credentials] = None) -> List[EmbeddingModel]:
    """The endpoint's embedding models a collection can use, its
    OPENAI_EMBEDDING_MODEL first; none without an endpoint."""
    if creds is None or not _endpoint_configured(creds):
        return []
    provider = _openai()
    host = provider.endpoint(creds)
    return [
        EmbeddingModel(
            info.ref, f"Served by {host}: the rows are sent there to be embedded."
        )
        for info in provider.embedding_models(creds)
    ]


def get_collection_embedder(
    model_name: str, creds: Optional[Credentials] = None
) -> RetrievalEmbedder:
    """The endpoint model a collection is embedded with, on ``creds``. Raises
    :class:`EmbeddingModelError` when it can't run: a collection has no
    lexical fallback."""
    if not is_endpoint_model(model_name):
        raise EmbeddingModelError(
            f"{model_name} is a local model this server no longer runs: delete "
            "the collection and build it again with an endpoint model."
        )
    if creds is None or not _endpoint_configured(creds):
        raise EmbeddingModelError(
            f"{model_name} is a model of an OpenAI-compatible endpoint: add "
            "your API key (and endpoint) in Settings to use this collection."
        )
    return EndpointEmbedder(model_name[len(ENDPOINT_PREFIX) :], creds)


# --- Pure helpers --------------------------------------------------------------


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

    Each piece fits a model's input window, so the embedding covers all of it.
    Pieces under ``min_chars`` are dropped; a paragraph longer than
    ``max_chars`` on its own is hard-cut rather than lost.
    """
    bounds = sorted({0, len(text), *(m.start() for m in _HEADING.finditer(text))})
    sections = [text[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]

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
    for section, vector in zip(sections, section_vectors, strict=True):
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
