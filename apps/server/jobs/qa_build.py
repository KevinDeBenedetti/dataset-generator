"""The incremental Q&A build, and what every Q&A job shares.

A Q&A job (the GitHub Q&A, jobs/qa_dataset.py; the resume Q&A,
jobs/resume_qa.py) makes the next version of a dataset from the published one.
This module holds what that takes, whatever the pairs are about:

* the pairs and the dataset (:class:`QAPair`, :class:`QADataset`), cleaning,
  screening against the embedding model and grading by the LLM;
* reading the published version and publishing the next one, through the Hub
  dataset repo (services/hub_repo.py);
* :func:`build` — the build itself. A job hands it a :class:`SourcePlan` (its
  sources, its facts, the model calls for the sources that changed) and gets
  back a :class:`BuildResult`.

Generation goes through the model provider registry (services/providers), on
the OpenAI-compatible endpoint.
"""

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from server.core.config import config
from server.core.cpu import cpu_bound
from server.services.credentials import HF_TOKEN, Credentials
from server.services.hub_repo import (
    ROOT_PAIRS_PATH,
    DatasetMoved,
    HubDatasetRepo,
    HubRepoError,
    HubTokenMissing,
    open_repo,
)

from server.jobs.github_snapshot import (
    gather_limited,
)
from server.services.providers import (
    CompletionRequest as ProviderRequest,
    ProviderError,
    complete as provider_complete,
    get_provider,
    parse_ref,
)
from server.services.semantic import (
    get_embedder,
    Embedder,
    SemanticIndex,
    find_semantic_duplicate,
    grounding_scores,
    nearest_texts,
    split_sections,
    thresholds_of,
    uncovered_sections,
)

logger = logging.getLogger(__name__)


# Targeted generation (see guidance): how many existing questions a prompt
# lists as "don't ask again", the similarity under which a question is too far
# from the source to be worth listing, and how many uncovered sections (each
# cut to a one-line excerpt) the prompt points the LLM to.
MAX_AVOID_QUESTIONS = 15


AVOID_MIN_SIMILARITY = 0.3


MAX_FOCUS_SECTIONS = 5


FOCUS_SECTION_CHARS = 300


ANSWER_STYLE = (
    "Keep answers concise (1 to 3 sentences max) and rephrase them in your own "
    "words — never copy a passage verbatim from the given context. Each pair must "
    "cover a different aspect: no rewording the same question in another form."
)


JSON_FORMAT_INSTRUCTION = (
    "Respond ONLY with a compact JSON array (no extra whitespace, indentation, or "
    "line breaks), no surrounding text, in the format "
    '[{"question":"...","answer":"...","confidence":0.9}], where "confidence" is a '
    "score between 0 and 1 reflecting how well the given context supports the "
    "answer."
)


class JobError(RuntimeError):
    pass


@dataclass
class QAPair:
    question: str
    answer: str
    category: str
    repo: Optional[str] = None
    model: Optional[str] = None
    id: Optional[str] = None
    source: str = "github"
    confidence: Optional[float] = None
    # Source keys (see source_key) the pair was generated from — what lets the
    # next run keep it untouched while those sources are unchanged.
    sources: List[str] = field(default_factory=list)
    # Answer ↔ closest source chunk cosine (services/semantic.py).
    grounding: Optional[float] = None
    # The LLM's grade, 0-1, and its reason (grade_pairs).
    judge: Optional[float] = None
    judge_note: Optional[str] = None

    def to_record(self) -> dict:
        # Key order matches the TS exporter's records, keeping the Hub diff clean;
        # sources/grounding are additive fields, after the original ones.
        rec: Dict[str, Any] = {
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "category": self.category,
        }
        if self.repo:
            rec["repo"] = self.repo
        if self.model:
            rec["model"] = self.model
        if self.confidence is not None:
            rec["confidence"] = self.confidence
        if self.id:
            rec["id"] = self.id
        if self.sources:
            rec["sources"] = self.sources
        if self.grounding is not None:
            rec["grounding"] = self.grounding
        if self.judge is not None:
            rec["judge"] = self.judge
        if self.judge_note:
            rec["judge_note"] = self.judge_note
        return rec

    @classmethod
    def from_record(cls, rec: Any) -> Optional["QAPair"]:
        """Rebuild a pair from a published ``train.jsonl`` line; None if malformed."""
        if not isinstance(rec, dict):
            return None
        question, answer, category = (
            rec.get("question"),
            rec.get("answer"),
            rec.get("category"),
        )
        if not all(isinstance(v, str) and v for v in (question, answer, category)):
            return None
        sources = rec.get("sources")
        grounding = rec.get("grounding")
        return cls(
            question=question,
            answer=answer,
            category=category,
            repo=rec.get("repo") or None,
            model=rec.get("model") or None,
            id=rec.get("id") or None,
            source=rec.get("source") or "github",
            confidence=_confidence(rec.get("confidence")),
            sources=[s for s in sources if isinstance(s, str)]
            if isinstance(sources, list)
            else [],
            grounding=float(grounding)
            if isinstance(grounding, (int, float)) and not isinstance(grounding, bool)
            else None,
            judge=_confidence(rec.get("judge")),
            judge_note=rec.get("judge_note")
            if isinstance(rec.get("judge_note"), str)
            else None,
        )


@dataclass
class CompletionRequest:
    system: str
    user: str
    max_tokens: int


CompletionFn = Callable[[CompletionRequest], Awaitable[str]]


def provider_completion(model_ref: str, creds: Credentials) -> CompletionFn:
    """CompletionFn over the provider registry, for the ``model_ref`` model.

    A failed call raises :class:`ProviderError`: :func:`generate_pairs`
    retries it like an empty answer, and says why when nothing recovers.
    """

    async def complete(req: CompletionRequest) -> str:
        result = await provider_complete(
            model_ref,
            ProviderRequest(
                system=req.system, user=req.user, max_tokens=req.max_tokens
            ),
            creds,
        )
        return result.text

    return complete


# A provider's error, as a run reports it: enough for its status and message.
MAX_ERROR_CHARS = 400


def token_budget(pairs: int) -> int:
    return min(1500, 400 + pairs * 150)


def _extract_json_array(text: str) -> str:
    fenced = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    fenced = re.sub(r"```\s*$", "", fenced).strip()
    if fenced.startswith("["):
        return fenced
    start, end = fenced.find("["), fenced.rfind("]")
    return fenced[start : end + 1] if start != -1 and end > start else fenced


def _complete_objects(text: str) -> List[str]:
    """Top-level ``{...}`` objects, string-aware — salvages the complete pairs
    before a max-tokens cutoff (the cut object never closes its braces)."""
    objects: List[str] = []
    depth, start = 0, -1
    in_string = escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                objects.append(text[start : i + 1])
                start = -1
    return objects


def _to_pair(obj, repo: str, category: str, model: str) -> Optional[QAPair]:
    if not isinstance(obj, dict):
        return None
    question, answer = obj.get("question"), obj.get("answer")
    if not isinstance(question, str) or not isinstance(answer, str):
        return None
    if not question.strip() or not answer.strip():
        return None
    return QAPair(
        question=question.strip(),
        answer=answer.strip(),
        category=category,
        repo=repo,
        model=model,
        confidence=_confidence(obj.get("confidence")),
    )


def _confidence(value: Any) -> Optional[float]:
    """A model-reported score clamped to [0, 1]; None when absent or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        score = float(value)
    except ValueError:
        return None
    return round(min(1.0, max(0.0, score)), 3)


def parse_pairs(raw: str, repo: str, category: str, model: str) -> List[QAPair]:
    text = _extract_json_array(raw)
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("not a JSON array")
        return [p for p in (_to_pair(o, repo, category, model) for o in parsed) if p]
    except ValueError:
        salvaged = []
        for obj in _complete_objects(text):
            try:
                pair = _to_pair(json.loads(obj), repo, category, model)
            except ValueError:
                continue
            if pair:
                salvaged.append(pair)
        if salvaged:
            logger.warning(
                "%s: malformed LLM output, salvaged %d pair(s)", repo, len(salvaged)
            )
        else:
            logger.warning("%s: could not parse LLM output: %.200s", repo, raw)
        return salvaged


async def generate_pairs(
    complete: CompletionFn,
    req: CompletionRequest,
    repo: str,
    category: str,
    model: str,
) -> List[QAPair]:
    """Retry an empty or failed response once, then the whole request once more
    if nothing usable came out — a fresh generation beats salvaging a broken
    one. When none recovers, the error says why: the provider's own error when
    the last call failed (else only the worker's log would), or that the
    answers were empty or unparseable."""
    failure = ""
    for _ in range(2):
        raw = ""
        for _ in range(2):
            try:
                raw = await complete(req)
                failure = ""
            except ProviderError as exc:
                logger.warning("%s: the model call failed: %s", repo, exc)
                raw, failure = "", str(exc)
            if raw.strip():
                break
        # No answer at all (the calls failed): nothing to parse, or to log as
        # unparseable.
        pairs = parse_pairs(raw, repo, category, model) if raw.strip() else []
        if pairs:
            return pairs
    if failure:
        raise JobError(failure[:MAX_ERROR_CHARS])
    raise JobError("LLM returned no usable pairs (empty or unparseable) after retry")


def guidance(avoid: Sequence[str], focus: Sequence[str]) -> str:
    """Prompt tail steering the LLM off known questions, onto uncovered topics."""
    blocks: List[str] = []
    if avoid:
        blocks.append(
            "These questions already exist in the dataset — do NOT ask them "
            "again or rephrase them; ask about something else:\n"
            + "\n".join(f"- {q}" for q in avoid)
        )
    if focus:
        blocks.append(
            "No existing question covers these parts of the context yet — "
            "prioritize them:\n"
            + "\n".join("- " + " ".join(s.split())[:FOCUS_SECTION_CHARS] for s in focus)
        )
    return "".join(f"\n\n{b}" for b in blocks)


def dedupe_key(text: str) -> str:
    """Lowercased, accent- and punctuation-stripped."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in decomposed if not ("̀" <= c <= "ͯ"))
    return re.sub(r"[\W_]+", " ", stripped).strip()


def _is_low_quality(pair: QAPair) -> bool:
    if len(pair.question) < 8 or len(pair.answer) < 2:
        return True
    return dedupe_key(pair.question) == dedupe_key(pair.answer)


def pair_id(pair: QAPair) -> str:
    """Content-derived, so an unchanged pair keeps its id across runs."""
    key = f"{pair.category}:{pair.repo or ''}:{pair.question}"
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def sanitize_pairs(pairs: List[QAPair]) -> Tuple[List[QAPair], int]:
    """Drop trivial pairs, dedupe by normalized question (first wins), assign ids."""
    seen = set()
    out: List[QAPair] = []
    for pair in pairs:
        if _is_low_quality(pair):
            continue
        key = dedupe_key(pair.question)
        if not key or key in seen:
            continue
        seen.add(key)
        pair.id = pair_id(pair)
        out.append(pair)
    return out, len(pairs) - len(out)


@dataclass
class QADataset:
    pairs: List[QAPair]
    dropped: int
    errors: List[str]
    # Incremental-run accounting (see build_qa_dataset).
    kept: int = 0
    new: int = 0
    semantic_duplicates: int = 0
    review: List[QAPair] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)
    # Ids of the pairs generated this run (a subset of ``pairs``) — what a
    # draft review shows, as opposed to the pairs carried over.
    new_ids: List[str] = field(default_factory=list)
    # Pairs of the published version this draft no longer has (a source gone
    # or deselected, a fact that changed): what publishing it would delete.
    removed: List[QAPair] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe form, for storing an unpublished draft."""
        return {
            "pairs": [p.to_record() for p in self.pairs],
            "review": [p.to_record() for p in self.review],
            "removed": [p.to_record() for p in self.removed],
            "dropped": self.dropped,
            "errors": self.errors,
            "kept": self.kept,
            "new": self.new,
            "semantic_duplicates": self.semantic_duplicates,
            "manifest": self.manifest,
            "new_ids": self.new_ids,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QADataset":
        def pairs(key: str) -> List[QAPair]:
            return [p for p in map(QAPair.from_record, data.get(key, [])) if p]

        return cls(
            pairs=pairs("pairs"),
            dropped=data.get("dropped", 0),
            errors=list(data.get("errors", [])),
            kept=data.get("kept", 0),
            new=data.get("new", 0),
            semantic_duplicates=data.get("semantic_duplicates", 0),
            review=pairs("review"),
            manifest=dict(data.get("manifest", {})),
            new_ids=list(data.get("new_ids", [])),
            removed=pairs("removed"),
        )

    def with_selection(
        self,
        exclude: Sequence[str] = (),
        promote: Sequence[str] = (),
        edits: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> "QADataset":
        """This draft after a review: ``exclude`` drops new pairs from the
        export, ``promote`` moves pairs from the review list into it, and
        ``edits`` (id → question and answer) rewrites new or promoted pairs.

        An edited pair gets the id of its new content and loses its grounding
        score, computed for the model's answer, not the reviewer's. Pairs
        carried over from the published version are never edited here.
        """
        excluded = set(exclude) & set(self.new_ids)
        promoted = [p for p in self.review if p.id in set(promote)]
        kept_new = [i for i in self.new_ids if i not in excluded]
        editable = set(kept_new) | {p.id for p in promoted}
        changes = {k: v for k, v in (edits or {}).items() if k in editable}
        renamed: Dict[str, str] = {}

        def apply(pair: QAPair) -> QAPair:
            change = changes.get(pair.id or "")
            if not change:
                return pair
            edited = replace(
                pair,
                question=change["question"].strip(),
                answer=change["answer"].strip(),
                grounding=None,
                judge=None,
                judge_note=None,
            )
            edited.id = pair_id(edited)
            renamed[pair.id or ""] = edited.id
            return edited

        pairs: List[QAPair] = []
        seen: Set[str] = set()
        for pair in [p for p in self.pairs if p.id not in excluded] + promoted:
            pair = apply(pair)
            # An edit can turn a pair into another one's twin: keep the first.
            if pair.id and pair.id in seen:
                continue
            seen.add(pair.id or "")
            pairs.append(pair)
        new_ids = [renamed.get(i, i) for i in kept_new]
        new_ids += [renamed.get(p.id, p.id) for p in promoted if p.id]
        return QADataset(
            pairs=pairs,
            dropped=self.dropped,
            errors=self.errors,
            kept=self.kept,
            new=len(kept_new) + len(promoted),
            semantic_duplicates=self.semantic_duplicates,
            review=[p for p in self.review if p not in promoted],
            manifest=self.manifest,
            new_ids=[i for i in dict.fromkeys(new_ids) if i in seen],
            removed=self.removed,
        )


def removed_pairs(previous: "PreviousState", dataset: QADataset) -> List[QAPair]:
    """Pairs of the published version that the draft no longer holds, in
    its pairs or in its review list."""
    current = {p.id for p in dataset.pairs} | {p.id for p in dataset.review}
    return [p for p in previous.pairs if p.id and p.id not in current]


ProgressFn = Callable[[int, int, str], None]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class PreviousState:
    """The last published version: the job's own pairs and its source manifest."""

    pairs: List[QAPair] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)
    # The commit it was read at (None: the repo did not exist, or was not
    # read) — what a draft built on this version is published on top of.
    commit: Optional[str] = None


# Tells a job's own row from a foreign one (a pair added from a file, say):
# the pair when the row is the job's, else None.
OwnPair = Callable[[Dict[str, Any]], Optional[QAPair]]


_MOVED = (
    "The dataset '{repo}' changed on Hugging Face since this draft was generated. "
    "Start a new run: it builds on the current version. This draft is kept, "
    "unpublished."
)


def open_qa_repo(creds: Credentials, repo_id: str) -> HubDatasetRepo:
    """Open a Q&A job's dataset repo (services/hub_repo.py): the token is
    checked and a bare repo name completed. Every refusal is a JobError."""
    try:
        return open_repo(creds, repo_id, new_pairs_path=ROOT_PAIRS_PATH)
    except HubTokenMissing as exc:
        raise JobError(
            "Your Hugging Face token is required (add it in Settings)"
        ) from exc
    except HubRepoError as exc:
        raise JobError(str(exc)) from exc


def load_previous_state(repo: HubDatasetRepo, own: OwnPair) -> PreviousState:
    """The published version the next run builds on: the job's own pairs, the
    manifest's source hashes and the commit they were read at.

    A repo that does not exist, or has no rows yet, is a first run (empty
    state). Anything else — the Hub unreachable, a permission error, a file
    that cannot be read — raises: silently starting over would re-spend the
    whole generation budget.
    """
    try:
        version = repo.read()
    except Exception as exc:
        raise JobError(
            f"could not read the previous dataset from {repo.repo_id}: {exc} — "
            "run with full_refresh to regenerate from scratch"
        ) from exc

    pairs = [pair for pair in map(own, version.rows) if pair is not None]
    raw = (version.manifest or {}).get("sources", {})
    if isinstance(raw, dict):
        sources = {k: v for k, v in raw.items() if isinstance(v, str)}
    else:
        sources = {}
        logger.warning("unreadable manifest.json — treating every source as changed")
    logger.info(
        "previous version: %d pair(s), %d tracked source(s), %d foreign row(s)",
        len(pairs),
        len(sources),
        len(version.rows) - len(pairs),
    )
    return PreviousState(pairs, sources, version.commit)


async def read_published(
    creds: Credentials,
    repo_id: str,
    full_refresh: bool,
    own: OwnPair,
) -> Tuple[str, PreviousState]:
    """The dataset's full repo id and the version a run builds on.

    The repo is opened first — the token checked, before any model usage is
    spent — then read, unless ``full_refresh`` ignores what is published.
    """
    repo = await asyncio.to_thread(open_qa_repo, creds, repo_id)
    if full_refresh:
        logger.info("full refresh: ignoring the previously published version")
        return repo.repo_id, PreviousState()
    return repo.repo_id, await asyncio.to_thread(load_previous_state, repo, own)


@dataclass
class Source:
    key: str
    text: str
    changed: bool = True


def _chunks(texts: Sequence[str]) -> List[str]:
    chunks: List[str] = []
    for text in texts:
        chunks += split_sections(text) or ([text] if text.strip() else [])
    return chunks


def _grounding_for(
    embedder: Embedder, pairs: List[QAPair], sources: Dict[str, Source]
) -> List[float]:
    """Each pair's answer ↔ closest chunk of its own sources' current text."""
    by_text: Dict[Tuple[str, ...], Any] = {}
    scores: List[float] = []
    answers = embedder.embed([p.answer for p in pairs]) if pairs else []
    for pair, answer_vector in zip(pairs, answers, strict=True):
        keys = tuple(k for k in pair.sources if k in sources)
        if keys not in by_text:
            chunks = _chunks([sources[k].text for k in keys])
            by_text[keys] = embedder.embed(chunks) if chunks else []
        score = grounding_scores(answer_vector, by_text[keys])[0]
        scores.append(round(float(score), 3))
    return scores


def recheck_pairs(
    embedder: Optional[Embedder],
    recheck: List[QAPair],
    sources: Dict[str, Source],
    kept: List[QAPair],
    review: List[QAPair],
) -> None:
    """The pairs of changed sources, scored against the new text: kept when
    still grounded, else sent to review — every one kept without an embedder.
    Blocking (embeddings)."""
    if embedder is None or not recheck:
        kept.extend(recheck)
        return
    scores = _grounding_for(embedder, recheck, sources)
    for pair, score in zip(recheck, scores, strict=True):
        pair.grounding = score
        (kept if score >= thresholds_of(embedder).grounding else review).append(pair)


def question_index(
    embedder: Optional[Embedder], pairs: Sequence[QAPair]
) -> SemanticIndex:
    """The questions of ``pairs``, embedded: what a new question is checked
    against, and what a prompt is steered away from. Blocking."""
    index = SemanticIndex()
    if embedder is not None and pairs:
        questions = [p.question for p in pairs]
        index.add(questions, embedder.embed(questions))
    return index


def guidance_for(
    text: str, index: SemanticIndex, embedder: Embedder
) -> Tuple[List[str], List[str]]:
    """``(avoid, focus)`` for a prompt over ``text``: the existing questions
    nearest to it, and its sections no question covers yet. Blocking."""
    sections = _chunks([text])
    if not sections or not len(index):
        return [], []
    vectors = embedder.embed(sections)
    avoid = nearest_texts(vectors, index, MAX_AVOID_QUESTIONS, AVOID_MIN_SIMILARITY)
    uncovered = uncovered_sections(
        sections, vectors, index, thresholds_of(embedder).uncovered
    )
    # All sections uncovered says nothing the plain prompt doesn't.
    focus = uncovered[:MAX_FOCUS_SECTIONS] if len(uncovered) < len(sections) else []
    return avoid, focus


def screen_pairs(
    embedder: Optional[Embedder],
    fresh: List[QAPair],
    sources: Dict[str, Source],
    index: SemanticIndex,
    review: List[QAPair],
    errors: List[str],
) -> Tuple[List[QAPair], int]:
    """The generated pairs that make it in, and how many were rephrasings.

    A pair whose question is a rephrasing of an indexed one is dropped; one
    whose answer is far from its sources goes to ``review``; the rest are
    accepted and indexed in turn. Without an embedder, or when it fails
    mid-run (noted in ``errors``), every pair is accepted unscreened — the
    generation is done, its pairs are not lost to the checks. Blocking.
    """
    if embedder is None or not fresh:
        return fresh, 0
    try:
        vectors = embedder.embed([p.question for p in fresh])
        grounding = _grounding_for(embedder, fresh, sources)
    except Exception as exc:  # noqa: BLE001 — an endpoint can fail mid-run
        logger.warning("Semantic checks skipped: %s", exc)
        errors.append(
            f"Duplicate and grounding checks skipped ({embedder.model_name} "
            f"failed): {exc}"
        )
        return fresh, 0
    accepted: List[QAPair] = []
    duplicates = 0
    thresholds = thresholds_of(embedder)
    for pair, vector, score in zip(fresh, vectors, grounding, strict=True):
        match = find_semantic_duplicate(vector, index, thresholds.dedup)
        if match is not None:
            duplicates += 1
            logger.info(
                "rephrasing (%.2f) of %r dropped: %r",
                match[1],
                index.texts[match[0]],
                pair.question,
            )
            continue
        pair.grounding = score
        if score < thresholds.grounding:
            review.append(pair)
            logger.info(
                "far from its source (%.2f), to review: %r", score, pair.question
            )
            continue
        index.add([pair.question], vector)
        accepted.append(pair)
    return accepted, duplicates


# A new pair the LLM grades below this is held out for review, with its reason.
# Grading calls made at once.
GRADE_CONCURRENCY = 3
JUDGE_THRESHOLD = 0.6


JUDGE_CONTEXT_CHARS = 6000


JUDGE_RUBRIC = (
    "You grade question/answer pairs for a dataset that tests and feeds a "
    "portfolio chatbot. Grade each pair from 0 to 1: 1 when every claim of the "
    "answer is supported by the context, a recruiter or visitor would ask the "
    "question, and the question names its subject (never 'this project' or a "
    "pronoun alone); lower for each point that fails; 0 for an answer the "
    "context contradicts. Respond ONLY with a JSON array covering every pair, "
    '[{"id":"...","score":0.8,"reason":"a few words"}].'
)


def _parse_grades(raw: str) -> Dict[str, Tuple[float, str]]:
    """``id -> (score, reason)`` from a grader's answer; what can't be read is
    left out (those pairs stay ungraded)."""
    text = _extract_json_array(raw)
    try:
        parsed = json.loads(text)
        objects = parsed if isinstance(parsed, list) else []
    except ValueError:
        objects = []
        for obj in _complete_objects(text):
            try:
                objects.append(json.loads(obj))
            except ValueError:
                continue
    grades: Dict[str, Tuple[float, str]] = {}
    for obj in objects:
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
            continue
        score = _confidence(obj.get("score"))
        if score is None:
            continue
        reason = obj.get("reason")
        grades[obj["id"]] = (
            score,
            reason.strip()[:200] if isinstance(reason, str) else "",
        )
    return grades


def embedding_checks(
    embedder: Optional[Embedder], fresh: Sequence[QAPair], recheck: Sequence[QAPair]
) -> Optional[Dict[str, int]]:
    """What the embedding checks worked on this run, for the manifest: the new
    pairs screened (rephrasings, grounding) and the changed sources' old pairs
    re-checked. None without an embedder (the words were compared)."""
    if embedder is None:
        return None
    return {"compared": len(fresh), "rechecked": len(recheck)}


def embedding_summary(manifest: Dict[str, Any]) -> Optional[str]:
    """:func:`embedding_checks` in a few words, for a run's result — None for a
    draft made before the checks were recorded."""
    if "embedding_checks" not in manifest:
        return None
    checks = manifest["embedding_checks"]
    if checks is None:
        return "off: no embedding model, the words are compared"
    compared, rechecked = checks.get("compared", 0), checks.get("rechecked", 0)
    if not compared and not rechecked:
        return "nothing new to compare"
    parts = []
    if compared:
        parts.append(f"{compared} new pair(s) checked for rephrasings and grounding")
    if rechecked:
        parts.append(f"{rechecked} changed pair(s) re-checked against their source")
    return ", ".join(parts)


async def grade_pairs(
    grader: CompletionFn,
    pairs: List[QAPair],
    sources: Dict[str, "Source"],
    review: List[QAPair],
    errors: List[str],
    *,
    rubric: str = JUDGE_RUBRIC,
    context_chars: int = JUDGE_CONTEXT_CHARS,
    outcome: str = "to review",
) -> List[QAPair]:
    """Grade new pairs with the LLM, one call per group sharing their sources
    (a section's items, a repo's docs batch), against those sources' text.

    Returns the pairs graded :data:`JUDGE_THRESHOLD` or above, and those it
    couldn't grade (a failed call is noted in ``errors``: the pairs are kept,
    not lost to the check); the others go to ``review``, their grade and its
    reason recorded (``judge``, ``judge_note``). ``outcome`` names what the
    caller does with those in the log ("dropped" when it discards them)."""
    groups: Dict[Tuple[str, ...], List[QAPair]] = {}
    for pair in pairs:
        groups.setdefault(tuple(pair.sources), []).append(pair)

    async def grade(keys: Tuple[str, ...], group: List[QAPair]) -> None:
        context = "\n\n".join(sources[k].text for k in keys if k in sources)
        listing = "\n".join(
            json.dumps(
                {"id": p.id, "question": p.question, "answer": p.answer},
                ensure_ascii=False,
            )
            for p in group
        )
        req = CompletionRequest(
            system=rubric,
            user=f"Context:\n{context[:context_chars]}\n\nPairs:\n{listing}",
            max_tokens=min(1500, 200 + 80 * len(group)),
        )
        try:
            raw = await grader(req)
        except ProviderError as exc:
            errors.append(
                f"Grading skipped for {len(group)} pair(s): {str(exc)[:MAX_ERROR_CHARS]}"
            )
            return
        grades = _parse_grades(raw)
        for pair in group:
            if pair.id in grades:
                pair.judge, pair.judge_note = grades[pair.id]

    await gather_limited(GRADE_CONCURRENCY, [grade(k, g) for k, g in groups.items()])
    kept: List[QAPair] = []
    for pair in pairs:
        if pair.judge is not None and pair.judge < JUDGE_THRESHOLD:
            review.append(pair)
            logger.info(
                "graded %.2f (%s), %s: %r",
                pair.judge,
                pair.judge_note,
                outcome,
                pair.question,
            )
        else:
            kept.append(pair)
    return kept


# --- the build ----------------------------------------------------------------


@dataclass
class Task:
    """One model call over sources that changed.

    ``label`` names the call in an error ("<label>: <what failed>");
    ``context`` is the text the call is made over, from which :func:`build`
    works out its guidance; ``run(avoid, focus)`` makes the call and returns
    its pairs, raising :class:`JobError` when it fails.
    """

    keys: List[str]
    label: str
    context: str
    run: Callable[[List[str], List[str]], Awaitable[List[QAPair]]]
    avoid: List[str] = field(default_factory=list)
    focus: List[str] = field(default_factory=list)
    failed: bool = False


@dataclass
class TaskGroup:
    """Tasks made one after another (a repo's calls, a resume section's):
    groups run side by side, and progress counts them. ``name`` is what the
    progress shows."""

    name: str
    tasks: List[Task]


def _never(_: Any) -> bool:
    return False


@dataclass
class SourcePlan:
    """What a Q&A job hands :func:`build`: what it generates from, and how.

    ``sources`` are every source of this run, by key. ``facts`` are rebuilt
    every run and never carried over. ``groups()`` is called once the sources
    are marked changed or not, and returns the model calls for the changed
    ones. ``sources_of(pair)`` gives the source keys a published pair was
    generated from — None for a pair the build does not carry (a fact, a pair
    the job handles itself).

    A source that still exists but is not part of this run (a repo beyond
    ``max_repos``, one that could not be read) keeps what it has:
    ``outside_pair`` says so of a published pair, kept as it is, and
    ``outside_source`` of a manifest key, whose hash is kept.
    """

    sources: Dict[str, Source]
    facts: List[QAPair]
    groups: Callable[[], List[TaskGroup]]
    sources_of: Callable[[QAPair], Optional[List[str]]]
    concurrency: int = 3
    outside_pair: Callable[[QAPair], bool] = _never
    outside_source: Callable[[str], bool] = _never


@dataclass
class BuildResult:
    """What :func:`build` made. The dataset's pairs are ``existing`` (the
    facts, then the pairs carried over) followed by ``accepted`` (the new
    pairs that passed every check)."""

    existing: List[QAPair]
    accepted: List[QAPair]
    review: List[QAPair]
    errors: List[str]
    dropped: int
    semantic_duplicates: int
    # Pairs carried over from the published version (the facts are not).
    kept: int
    # Sources whose text moved since the published version.
    changed: int
    # For the embedding summary: the new pairs screened, the old ones re-checked.
    fresh: List[QAPair]
    recheck: List[QAPair]
    _hashes: Dict[str, str]
    _previous: Dict[str, str]
    _carried: Dict[str, str]
    _failed: Set[str]

    def source_hashes(self, failed: Sequence[str] = ()) -> Dict[str, str]:
        """The manifest's ``sources``. A source whose call failed (the build's
        own, plus ``failed``) keeps its previous hash, or none, so the next
        run retries it instead of believing it up to date."""
        not_done = self._failed | set(failed)
        hashes = dict(self._carried)
        for key, value in self._hashes.items():
            if key not in not_done:
                hashes[key] = value
            elif key in self._previous:
                hashes[key] = self._previous[key]
        return dict(sorted(hashes.items()))

    def manifest(
        self, embedder: Optional[Embedder], failed: Sequence[str] = ()
    ) -> Dict[str, Any]:
        """The part of ``manifest.json`` every Q&A dataset has."""
        return {
            "embedding_model": embedder.model_name if embedder else None,
            "embedding_checks": embedding_checks(embedder, self.fresh, self.recheck),
            "sources": self.source_hashes(failed),
        }


async def build(
    plan: SourcePlan,
    previous: PreviousState,
    *,
    embedder: Optional[Embedder] = None,
    grader: Optional[CompletionFn] = None,
    on_progress: Optional[ProgressFn] = None,
) -> BuildResult:
    """Build the next version of a dataset from ``previous`` (empty: a full run).

    1. Every source is hashed; an unchanged one keeps its pairs, with no model
       call. The pairs of a source that is gone are dropped; those of a source
       outside this run are carried over as they are.
    2. A changed source's old pairs are re-checked against its new text (kept
       when still grounded, else sent to review), then it is regenerated with
       the nearest existing questions as "don't ask again" and its uncovered
       sections as "prioritize".
    3. New pairs are deduplicated — normalized text, then embedding cosine
       against every kept pair — held out for review when their answer is far
       from the source, then graded by ``grader``.

    The embedding parts are skipped without an ``embedder``, and when nothing
    changed: a run with no model call to make embeds no question.
    ``on_progress(done, total, name)`` is called as each group is generated.
    """
    sources = plan.sources
    for src in sources.values():
        src.changed = previous.sources.get(src.key) != content_hash(src.text)

    # Previous pairs: carried over, re-checked, or dropped.
    kept: List[QAPair] = []
    recheck: List[QAPair] = []
    for pair in previous.pairs:
        if plan.outside_pair(pair):
            kept.append(pair)
            continue
        keys = [k for k in plan.sources_of(pair) or [] if k in sources]
        if not keys:
            continue
        pair.sources = keys
        (recheck if any(sources[k].changed for k in keys) else kept).append(pair)

    groups = plan.groups()
    tasks = [task for group in groups for task in group.tasks]
    review: List[QAPair] = []
    errors: List[str] = []

    def prepare() -> SemanticIndex:
        recheck_pairs(embedder, recheck, sources, kept, review)
        if embedder is None or not tasks:
            return SemanticIndex()  # nothing to generate: no embedding spent
        # The facts are in the index too, so a model's rephrasing of one is
        # dropped as a duplicate.
        index = question_index(embedder, plan.facts + kept)
        for task in tasks:
            task.avoid, task.focus = guidance_for(task.context, index, embedder)
        return index

    carried = len(kept)
    index = await cpu_bound(prepare)  # embedding batches: core/cpu.py
    changed = sum(s.changed for s in sources.values())
    logger.info(
        "%d source(s) changed of %d; %d pair(s) carried over, %d re-checked "
        "(%d to review), %d model call(s) to make",
        changed,
        len(sources),
        carried,
        len(recheck),
        len(review),
        len(tasks),
    )

    done = 0
    if on_progress is not None:
        on_progress(0, len(groups), "")

    async def for_group(group: TaskGroup) -> List[QAPair]:
        nonlocal done
        pairs: List[QAPair] = []
        for task in group.tasks:
            try:
                pairs += await task.run(task.avoid, task.focus)
            except JobError as exc:
                task.failed = True
                errors.append(f"{task.label}: {exc}")
        done += 1
        logger.info("  [%d/%d] %s", done, len(groups), group.name)
        if on_progress is not None:
            on_progress(done, len(groups), group.name)
        return pairs

    generated: List[QAPair] = []
    for pairs in await gather_limited(
        plan.concurrency, [for_group(group) for group in groups]
    ):
        generated += pairs

    # Existing pairs first, so a regenerated question never displaces one.
    clean, dropped = sanitize_pairs(plan.facts + kept + generated)
    fresh_ids = {id(p) for p in generated}
    existing = [p for p in clean if id(p) not in fresh_ids]
    fresh = [p for p in clean if id(p) in fresh_ids]

    accepted, semantic_duplicates = await cpu_bound(  # embedding batches: core/cpu.py
        screen_pairs, embedder, fresh, sources, index, review, errors
    )
    if grader is not None:
        accepted = await grade_pairs(grader, accepted, sources, review, errors)

    fact_ids = {id(p) for p in plan.facts}
    kept_count = sum(id(p) not in fact_ids for p in existing)
    logger.info(
        "%d pair(s): %d kept, %d new; %d dropped, %d rephrasing(s), %d to review, "
        "%d error(s)",
        len(existing) + len(accepted),
        kept_count,
        len(accepted),
        dropped,
        semantic_duplicates,
        len(review),
        len(errors),
    )
    return BuildResult(
        existing=existing,
        accepted=accepted,
        review=review,
        errors=errors,
        dropped=dropped,
        semantic_duplicates=semantic_duplicates,
        kept=kept_count,
        changed=changed,
        fresh=fresh,
        recheck=recheck,
        _hashes={key: content_hash(src.text) for key, src in sources.items()},
        _previous=dict(previous.sources),
        _carried={k: v for k, v in previous.sources.items() if plan.outside_source(k)},
        _failed={key for task in tasks if task.failed for key in task.keys},
    )


# --- Hugging Face export -------------------------------------------------------


def foreign_note(foreign: int) -> str:
    """The card's line about the rows a Q&A job did not generate."""
    if not foreign:
        return ""
    return (
        f"- {foreign} more row(s) come from another source (added from a file "
        "or a web page): kept as they are, and not counted above.\n"
    )


def size_category(n: int) -> str:
    if n < 1_000:
        return "n<1K"
    if n < 10_000:
        return "1K<n<10K"
    if n < 100_000:
        return "10K<n<100K"
    return "100K<n<1M"


def to_records(pairs: Sequence[QAPair]) -> List[Dict[str, Any]]:
    """The pairs as published rows, ordered by id so a version's diff on the
    Hub shows only what changed."""
    return [p.to_record() for p in sorted(pairs, key=lambda p: p.id or "")]


def publish_dataset(
    creds: Credentials,
    dataset: QADataset,
    repo_id: str,
    *,
    own: OwnPair,
    card: Callable[[int], str],
    commit_message: str,
    base_commit: Optional[str] = None,
) -> dict:
    """Publish the dataset to its private repo in one commit: ``train.jsonl``,
    ``review.jsonl``, ``manifest.json`` and the card — the manifest is what the
    next run diffs against, so it never lands without the pairs it describes.

    The repo's foreign rows (``own`` tells them apart) are published back as
    they are, after the job's pairs; ``card`` builds the card from their
    number. ``base_commit`` is the commit the draft was built on ("" for a
    repo that did not exist): a repo that is no longer there has moved, and
    nothing is written. None skips that check — a full refresh, or a draft
    stored before commits were recorded.
    """
    if not dataset.pairs:
        raise JobError("generated 0 pairs — refusing to publish an empty dataset")

    repo = open_qa_repo(creds, repo_id)
    moved = JobError(_MOVED.format(repo=repo.repo_id))
    try:
        current = repo.read()
        if base_commit is not None and (current.commit or "") != base_commit:
            raise moved
        foreign = [row for row in current.rows if own(row) is None]
        published = repo.publish(
            current,
            to_records(dataset.pairs) + foreign,
            card=card(len(foreign)),
            message=commit_message,
            review=to_records(dataset.review),
            manifest=dataset.manifest,
        )
    except DatasetMoved as exc:
        raise moved from exc
    except HubRepoError as exc:
        raise JobError(str(exc)) from exc
    return {
        "repo": repo.repo_id,
        "url": published.url,
        "records": len(dataset.pairs),
        "dropped": dataset.dropped,
    }


# --- generate, review, publish ------------------------------------------------


@dataclass
class Draft:
    """A generated, not yet published version of the dataset."""

    dataset: QADataset
    username: str
    repo_id: str
    full_refresh: bool
    model_ref: str
    # The commit of the published version this draft was built on ("": the
    # repo did not exist). None: not recorded — a full refresh, an older draft.
    base_commit: Optional[str] = None
    # The run changed nothing: the same pairs with the same answers as the
    # published version, and none held out. Known right after a generation
    # only (it is not stored with the draft).
    same_as_published: bool = False

    def stats(self) -> Dict[str, Any]:
        return {
            "records": len(self.dataset.pairs),
            "dropped": self.dataset.dropped,
            "errors": self.dataset.errors,
            "kept": self.dataset.kept,
            "new": self.dataset.new,
            "semantic_duplicates": self.dataset.semantic_duplicates,
            "review": len(self.dataset.review),
            "removed": len(self.dataset.removed),
            "full_refresh": self.full_refresh,
            "model": self.model_ref,
            "embedding_model": self.dataset.manifest.get("embedding_model"),
            "embedding_checks": embedding_summary(self.dataset.manifest),
        }


def base_of(previous: PreviousState, full_refresh: bool) -> Optional[str]:
    """The ``base_commit`` of a draft built on ``previous``."""
    return None if full_refresh else (previous.commit or "")


def model_for(
    creds: Credentials, model_ref: Optional[str], complete: Optional[CompletionFn]
) -> Tuple[str, str]:
    """``(model_ref, model)``, checked usable before anything is spent: the
    run's model, else OPENAI_LLM_MODEL."""
    model_ref = model_ref or config.openai_llm_model
    if not model_ref:
        raise JobError(
            "No LLM configured: set OPENAI_LLM_MODEL, or pick one on the Models page"
        )
    provider_name, model = parse_ref(model_ref)
    try:
        provider = get_provider(provider_name)
    except ProviderError as exc:
        raise JobError(str(exc)) from exc
    if complete is None and not provider.configured(creds):
        raise JobError(
            f"{' or '.join(provider.missing(creds))} is required to run {model_ref}"
        )
    return model_ref, model


# --- a run ---------------------------------------------------------------------


@dataclass
class Run:
    """What :func:`generate_draft` prepared for a job's build: the published
    version to build on, the model and how to call it, the embedding model."""

    previous: PreviousState
    complete: CompletionFn
    model: str
    embedder: Optional[Embedder]


async def generate_draft(
    creds: Credentials,
    repo_id: str,
    own: OwnPair,
    make: Callable[[Run], Awaitable[Tuple[QADataset, str]]],
    *,
    missing_repo: str,
    full_refresh: bool = False,
    model_ref: Optional[str] = None,
    complete: Optional[CompletionFn] = None,
) -> Draft:
    """Generate the next version of a Q&A dataset, without publishing it.

    Everything a run needs is checked before anything is spent: the model
    (``model_ref``, default ``OPENAI_LLM_MODEL``), the Hugging Face token and
    the dataset repo — ``missing_repo`` is the error when ``repo_id`` is blank.
    The run is incremental against the published version, read with ``own``
    telling the job's rows apart; ``full_refresh`` ignores it.

    ``make(run)`` is the job's part: it builds the dataset and says whose it is
    (the name on its card). The draft then lists the published pairs it no
    longer has, and records the commit it was built on.
    """
    model_ref, model = model_for(creds, model_ref, complete)
    if not creds.has(HF_TOKEN):
        raise JobError("Your Hugging Face token is required (add it in Settings)")
    if not repo_id.strip():
        raise JobError(missing_repo)
    repo_id, previous = await read_published(creds, repo_id, full_refresh, own)
    embedder = await asyncio.to_thread(get_embedder, creds)
    complete = complete or provider_completion(model_ref, creds)

    dataset, whose = await make(Run(previous, complete, model, embedder))
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)
    dataset.removed = removed_pairs(previous, dataset)
    same = (
        not full_refresh
        and previous.commit is not None
        and not dataset.review
        and {(p.id, p.answer) for p in previous.pairs}
        == {(p.id, p.answer) for p in dataset.pairs}
    )
    return Draft(
        dataset,
        whose,
        repo_id,
        full_refresh,
        model_ref,
        base_of(previous, full_refresh),
        same_as_published=same,
    )
