"""Local sentence embeddings for QA generation — no API call, no GPU.

The vector collections (``services/collections.py``) are embedded here too,
with one of :data:`COLLECTION_MODELS`.

Backs four checks shared by the in-app pipeline (``services/qa.py``) and the
GitHub Q&A jobs (``jobs/qa_dataset.py``):

* **semantic dedup** — a new question whose cosine to an existing one reaches
  the threshold is a rephrasing, not a new pair;
* **targeted prompts** — the existing questions nearest a source are fed back
  to the LLM as "do not ask these again";
* **uncovered topics** — source sections no question is close to are the
  topics to ask about next;
* **answer grounding** — an answer far from every chunk of its source is a
  hallucination signal, flagged for review.

The model runs through FastEmbed (ONNX Runtime, no torch), downloaded from the
Hugging Face Hub on first use and cached under ``FASTEMBED_CACHE_PATH`` — or,
with ``OPENAI_EMBEDDING_MODEL``, on the caller's OpenAI-compatible endpoint
(:class:`EndpointEmbedder`, a model named ``openai:<id>``; :func:`get_embedder`
picks). Everything here except the loaders is pure and takes an
:class:`Embedder` or plain vectors, so tests inject a fake and never download a
model. Vectors are L2-normalised on the way out: cosine is a dot product.
"""

import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, cast

import numpy as np

from server.core.config import config
from server.services.credentials import Credentials
from server.services.providers import get_provider
from server.services.providers.openai import OpenAIProvider, connection_key

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

    # A retrieval model may embed what is searched and what searches it
    # differently (a prefix, a task); FastEmbed applies the model's own rule.

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return normalize(np.array(list(self._model.passage_embed(list(texts)))))

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return normalize(np.array(list(self._model.query_embed(list(texts)))))


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


# --- Endpoint embeddings (OPENAI_EMBEDDING_MODEL) ---------------------------------

# A model named "openai:<id>" is served by the OpenAI-compatible endpoint; any
# other name is a local FastEmbed model.
ENDPOINT_PREFIX = "openai:"


def is_endpoint_model(name: str) -> bool:
    return name.startswith(ENDPOINT_PREFIX)


def _openai() -> OpenAIProvider:
    # The registry's instance: its discovery cache lists the endpoint's models.
    return cast(OpenAIProvider, get_provider("openai"))


def _endpoint_configured(creds: Optional[Credentials]) -> bool:
    return creds is not None and _openai().configured(creds)


class EndpointEmbedder:
    """An embedding model of the caller's OpenAI-compatible endpoint.

    Blocking like the local one (callers run it in a thread); ``remote`` tells
    them it waits on the network, not on the CPU. A failed call raises
    :class:`EmbeddingModelError`, its message safe to show.
    """

    remote = True

    def __init__(self, model_id: str, creds: Credentials):
        self.model_id = model_id
        self.model_name = ENDPOINT_PREFIX + model_id
        self.creds = creds

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
        logger.warning("%s, using the local embedding model instead", exc)
    with _probe_lock:
        _probed[key] = (ok, time.monotonic())
    return ok


def default_embedding_model(creds: Optional[Credentials]) -> str:
    """What embeds for ``creds`` by default: ``openai:<OPENAI_EMBEDDING_MODEL>``
    when they have an endpoint, else the local SEMANTIC_MODEL. (Unprobed: the
    checks fall back to the local model when the endpoint can't embed.)"""
    if config.openai_embedding_model and _endpoint_configured(creds):
        return ENDPOINT_PREFIX + config.openai_embedding_model
    return config.semantic_model


def get_embedder(creds: Optional[Credentials] = None) -> Optional[Embedder]:
    """The embedder of the duplicate, grounding and coverage checks for ``creds``.

    OPENAI_EMBEDDING_MODEL on the caller's endpoint when they have one and it
    answers, else the local model (:func:`get_local_embedder`), else ``None``
    — the lexical path. Blocking (a probe, a model load): call it in a thread.
    """
    if not config.semantic_enabled:
        return None
    model_id = config.openai_embedding_model
    if model_id and creds is not None and _endpoint_configured(creds):
        embedder = EndpointEmbedder(model_id, creds)
        if _answers(embedder):
            return embedder
    return get_local_embedder()


# --- Collection models (services/collections.py) --------------------------------


class RetrievalEmbedder(Protocol):
    """What a vector collection is built and searched with."""

    model_name: str

    def embed_passages(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_queries(self, texts: Sequence[str]) -> np.ndarray: ...


class EmbeddingModelError(RuntimeError):
    """A collection's model could not be loaded (no network, full disk)."""


@dataclass(frozen=True)
class EmbeddingModel:
    """A model a vector collection can be embedded with: local (CPU only), or
    served by the caller's OpenAI-compatible endpoint (``provider="openai"``,
    named ``openai:<id>``)."""

    name: str
    dimensions: Optional[int]
    size_mb: Optional[int]
    languages: str
    description: str
    provider: str = "local"


# Small models only: a build embeds every row of a split on the worker's CPU,
# and a search embeds its query in the API process. Anything else is refused,
# so a request can't make the server download gigabytes.
COLLECTION_MODELS: Tuple[EmbeddingModel, ...] = (
    EmbeddingModel(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        384,
        220,
        "50+ languages",
        "The model of the app's own duplicate checks, already in the image.",
    ),
    EmbeddingModel(
        "BAAI/bge-small-en-v1.5",
        384,
        67,
        "English",
        "Small and tuned for retrieval.",
    ),
    EmbeddingModel(
        "BAAI/bge-base-en-v1.5",
        768,
        210,
        "English",
        "Tuned for retrieval: more accurate than the small one, and slower.",
    ),
    EmbeddingModel(
        "sentence-transformers/all-MiniLM-L6-v2",
        384,
        90,
        "English",
        "The fastest.",
    ),
)


def collection_models(creds: Optional[Credentials] = None) -> List[EmbeddingModel]:
    """The models a collection can use, the default first: with an endpoint,
    its OPENAI_EMBEDDING_MODEL and the other embedding models its discovery
    found, then the local ones — the deployment's SEMANTIC_MODEL first."""
    return [*_endpoint_models(creds), *_local_models()]


def _endpoint_models(creds: Optional[Credentials]) -> List[EmbeddingModel]:
    if creds is None or not _endpoint_configured(creds):
        return []
    provider = _openai()
    host = provider.endpoint(creds)
    return [
        EmbeddingModel(
            info.ref,
            None,
            None,
            "",
            f"Served by {host}: the rows are sent there to be embedded.",
            provider="openai",
        )
        for info in provider.embedding_models(creds)
    ]


def _local_models() -> List[EmbeddingModel]:
    models = list(COLLECTION_MODELS)
    names = [m.name for m in models]
    if config.semantic_model in names:
        models.insert(0, models.pop(names.index(config.semantic_model)))
    elif config.semantic_model:
        models.insert(
            0,
            EmbeddingModel(
                config.semantic_model,
                None,
                None,
                "",
                "The model of the app's own duplicate checks (SEMANTIC_MODEL).",
            ),
        )
    return models


# Each loaded model holds 100-500 MB: a process keeps the two last used.
_MAX_LOADED = 2
_loaded_lock = threading.Lock()
_loaded: "OrderedDict[str, LocalEmbedder]" = OrderedDict()


def get_collection_embedder(
    model_name: str, creds: Optional[Credentials] = None
) -> RetrievalEmbedder:
    """The model a collection is embedded with: a local one is loaded (and
    downloaded) on first use, an endpoint one (``openai:<id>``) runs on
    ``creds``. Unlike :func:`get_local_embedder` it raises
    :class:`EmbeddingModelError` when the model can't load: a collection has no
    lexical fallback."""
    if is_endpoint_model(model_name):
        if creds is None or not _endpoint_configured(creds):
            raise EmbeddingModelError(
                f"{model_name} is a model of an OpenAI-compatible endpoint: add "
                "your API key (and endpoint) in Settings to use this collection."
            )
        return EndpointEmbedder(model_name[len(ENDPOINT_PREFIX) :], creds)
    if model_name == config.semantic_model:
        shared = _embedder  # already loaded for the duplicate checks
        if shared is not None:
            return shared
    with _loaded_lock:
        model = _loaded.get(model_name)
        if model is not None:
            _loaded.move_to_end(model_name)
            return model
        try:
            model = LocalEmbedder(model_name, config.fastembed_cache_path or None)
        except Exception as exc:  # noqa: BLE001 — reported to the caller below
            logger.warning("Embedding model %s unavailable: %s", model_name, exc)
            raise EmbeddingModelError(
                f"The embedding model {model_name} could not be loaded. The server "
                "downloads it from Hugging Face on first use: check its network "
                "access and the space left in FASTEMBED_CACHE_PATH."
            ) from None
        logger.info("Loaded embedding model %s for collections", model_name)
        _loaded[model_name] = model
        while len(_loaded) > _MAX_LOADED:
            _loaded.popitem(last=False)
        return model


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
