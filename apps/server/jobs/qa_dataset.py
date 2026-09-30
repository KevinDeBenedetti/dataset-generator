"""GitHub Q&A dataset → private Hugging Face dataset.

    python -m server.jobs.qa_dataset

Profile facts become pairs deterministically; each notable repo gets one
"overview" LLM call (description + README) plus one call per small batch of
its ``docs/`` files. The result is deduplicated and pushed to
HF_QA_DATASET_REPO as ``train.jsonl`` + a dataset card — the file the
portfolio's "Synchroniser les paires Q/R" action ingests.

Generation goes through the model provider registry (services/providers):
by default the Claude subscription via the Claude Agent SDK, authenticated
with CLAUDE_CODE_OAUTH_TOKEN (``claude setup-token``) — that subscription
grants no plain-API access, only Claude Code, which is what the SDK drives.
Any model reference works (QA_JOB_MODEL, or the one picked on the Jobs page),
including the OpenAI-compatible API.

Ported from portfolio-next (``scripts/generate-and-export-qa-dataset.ts``,
``src/lib/rag/github-qa.ts``, ``src/lib/rag/github-hf-export.ts``).
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from server.core.config import _env, config
from server.jobs.github_snapshot import (
    CorpusGitHubClient,
    GitHubProfile,
    GitHubSnapshot,
    RepoData,
    RepoDoc,
    fetch_repo_docs,
    fetch_snapshot,
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
    Embedder,
    SemanticIndex,
    find_semantic_duplicate,
    get_local_embedder,
    grounding_scores,
    nearest_texts,
    split_sections,
    uncovered_sections,
)

logger = logging.getLogger(__name__)

REPO_CONCURRENCY = 3
BASE_PAIRS_PER_REPO = 3
DOCS_BATCH_SIZE = 3
PAIRS_PER_DOC = 2
DOCS_BATCH_CHAR_BUDGET = 6000
MAX_DOCS_PER_REPO = 8
MAX_DOC_CHARS = 3000

# Targeted generation (see _guidance): how many existing questions a prompt
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

CATEGORIES = ("profile", "overview", "docs")


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
        )


@dataclass
class CompletionRequest:
    system: str
    user: str
    max_tokens: int


CompletionFn = Callable[[CompletionRequest], Awaitable[str]]


def provider_completion(model_ref: str) -> CompletionFn:
    """CompletionFn over the provider registry, for the ``model_ref`` model.

    A failed call degrades to '' so the retry-on-empty logic handles it.
    """

    async def complete(req: CompletionRequest) -> str:
        try:
            result = await provider_complete(
                model_ref,
                ProviderRequest(
                    system=req.system, user=req.user, max_tokens=req.max_tokens
                ),
            )
        except ProviderError as exc:
            logger.warning("%s query failed: %s", model_ref, exc)
            return ""
        return result.text

    return complete


def _token_budget(pairs: int) -> int:
    return min(1500, 400 + pairs * 150)


def profile_pairs(profile: Optional[GitHubProfile], repo_count: int) -> List[QAPair]:
    if not profile or not profile.login:
        return []
    who = profile.name or profile.login

    # Exact API facts, not model output — nothing to be unsure about.
    def pair(question: str, answer: str) -> QAPair:
        return QAPair(
            question=question, answer=answer, category="profile", confidence=1.0
        )

    pairs = [
        pair(f"What is {who}'s GitHub username?", f"@{profile.login}"),
        # Counts the indexed (non-fork, non-archived) repos rather than GitHub's
        # raw public_repos, which would contradict the repo list itself.
        pair(
            f"How many repositories does {who} have indexed in this knowledge base?",
            f"{repo_count} (excluding forks and archived repositories)",
        ),
    ]
    if profile.bio:
        pairs.append(
            pair(f"How does {who} describe themselves on GitHub?", profile.bio)
        )
    if profile.location:
        pairs.append(pair(f"Where is {who} based?", profile.location))
    if profile.company:
        pairs.append(pair(f"Which organization does {who} work for?", profile.company))
    if profile.blog:
        pairs.append(pair(f"What is {who}'s website or blog?", profile.blog))
    if profile.twitter:
        pairs.append(pair(f"What is {who}'s X/Twitter handle?", f"@{profile.twitter}"))
    pairs.append(
        pair(
            f"How many followers does {who} have on GitHub, and how many people "
            "do they follow?",
            f"{profile.followers} followers, {profile.following} following",
        )
    )
    return pairs


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
    """Retry an empty response once, then the whole request once more if nothing
    usable came out — a fresh generation beats salvaging a broken one."""
    for _ in range(2):
        raw = ""
        for _ in range(2):
            raw = await complete(req)
            if raw.strip():
                break
        pairs = parse_pairs(raw, repo, category, model)
        if pairs:
            return pairs
    raise JobError("LLM returned no usable pairs (empty or unparseable) after retry")


def _system_prompt(subject: str, focus: str) -> str:
    return (
        "You generate question/answer pairs in English for a fine-tuning dataset, "
        f"from {subject}. {JSON_FORMAT_INSTRUCTION} Answers must stay factual and "
        f"rely only on the given context. {ANSWER_STYLE} {focus}"
    )


def _guidance(avoid: Sequence[str], focus: Sequence[str]) -> str:
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


def overview_context(repo: RepoData) -> str:
    """The text an overview call is generated from (also what gets hashed)."""
    parts = [f"Repository: {repo.name}"]
    if repo.description:
        parts.append(f"Description: {repo.description}")
    if repo.language:
        parts.append(f"Primary language: {repo.language}")
    if repo.topics:
        parts.append(f"Topics: {', '.join(repo.topics)}")
    if repo.readme:
        parts.append(f"README (excerpt):\n{repo.readme[:1500]}")
    return "\n\n".join(parts)


async def overview_pairs(
    complete: CompletionFn,
    model: str,
    repo: RepoData,
    avoid: Sequence[str] = (),
    focus: Sequence[str] = (),
) -> List[QAPair]:
    context = overview_context(repo)
    pairs = await generate_pairs(
        complete,
        CompletionRequest(
            system=_system_prompt(
                "information about a GitHub repository",
                "Cover general angles: the project's purpose/motivation, its tech "
                "stack, and its overall architecture — no installation or "
                "configuration details, which belong to the documentation.",
            ),
            user=(
                f"Generate {BASE_PAIRS_PER_REPO} distinct question/answer pairs "
                f"from this context:\n\n{context}" + _guidance(avoid, focus)
            ),
            max_tokens=_token_budget(BASE_PAIRS_PER_REPO),
        ),
        repo.name,
        "overview",
        model,
    )
    for pair in pairs:
        pair.sources = [source_key(repo.name, "overview")]
    return pairs


def docs_batch_context(batch: List[RepoDoc]) -> Tuple[str, List[RepoDoc]]:
    """The documentation text a docs call sees, and the docs that made it in."""
    used = 0
    parts: List[str] = []
    included: List[RepoDoc] = []
    for doc in batch:
        if used >= DOCS_BATCH_CHAR_BUDGET:
            break
        remaining = DOCS_BATCH_CHAR_BUDGET - used
        content = (
            f"{doc.content[:remaining]}…"
            if len(doc.content) > remaining
            else doc.content
        )
        parts.append(f"### {doc.path}\n{content}")
        included.append(doc)
        used += len(content)
    return "\n\n".join(parts), included


async def docs_batch_pairs(
    complete: CompletionFn,
    model: str,
    repo: RepoData,
    batch: List[RepoDoc],
    avoid: Sequence[str] = (),
    focus: Sequence[str] = (),
) -> List[QAPair]:
    context, included = docs_batch_context(batch)
    if not included:
        return []

    want = len(batch) * PAIRS_PER_DOC
    pairs = await generate_pairs(
        complete,
        CompletionRequest(
            system=_system_prompt(
                "a GitHub repository's documentation",
                "Cover concrete angles: usage, configuration, detailed behaviour "
                "described in these files — one pair per notable point rather than "
                "summarizing the whole file in a single question.",
            ),
            user=(
                f"Repository: {repo.name}\n\nGenerate {want} distinct "
                f"question/answer pairs from this documentation:\n\n"
                + context
                + _guidance(avoid, focus)
            ),
            max_tokens=_token_budget(want),
        ),
        repo.name,
        "docs",
        model,
    )
    for pair in pairs:
        pair.sources = [source_key(repo.name, doc.path) for doc in included]
    return pairs


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
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


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

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe form, for storing an unpublished draft."""
        return {
            "pairs": [p.to_record() for p in self.pairs],
            "review": [p.to_record() for p in self.review],
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
        )

    def with_selection(
        self, exclude: Sequence[str] = (), promote: Sequence[str] = ()
    ) -> "QADataset":
        """This draft after a review: ``exclude`` drops new pairs from the
        export, ``promote`` moves pairs from the review list into it."""
        excluded = set(exclude) & set(self.new_ids)
        promoted = [p for p in self.review if p.id in set(promote)]
        kept_new = [i for i in self.new_ids if i not in excluded]
        return QADataset(
            pairs=[p for p in self.pairs if p.id not in excluded] + promoted,
            dropped=self.dropped,
            errors=self.errors,
            kept=self.kept,
            new=len(kept_new) + len(promoted),
            semantic_duplicates=self.semantic_duplicates,
            review=[p for p in self.review if p not in promoted],
            manifest=self.manifest,
            new_ids=kept_new + [p.id for p in promoted if p.id],
        )


ProgressFn = Callable[[int, int, str], None]


# --- Incremental state -------------------------------------------------------
#
# Each published version carries a manifest.json mapping every source (a repo's
# overview context, each of its docs/ files) to a hash of its content. The next
# run only calls the LLM for sources whose hash moved; the pairs of unchanged
# sources are carried over as they are.


def source_key(repo: str, part: str) -> str:
    """``"<repo>::overview"`` or ``"<repo>::<doc path>"``."""
    return f"{repo}::{part}"


def _source_repo(key: str) -> str:
    return key.split("::", 1)[0]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class PreviousState:
    """The last published version: its pairs and its source manifest."""

    pairs: List[QAPair] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)


def load_previous_state(api: Any, repo_id: str) -> PreviousState:
    """Read ``train.jsonl`` + ``manifest.json`` from the published dataset.

    A missing repo or file is a first run (empty state). Anything else — the
    Hub unreachable, a permission error — raises: silently starting over would
    re-spend the whole generation budget.
    """
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

    def read(filename: str) -> Optional[str]:
        try:
            path = api.hf_hub_download(
                repo_id=repo_id, filename=filename, repo_type="dataset"
            )
        except (EntryNotFoundError, RepositoryNotFoundError):
            return None
        return Path(path).read_text(encoding="utf-8")

    try:
        train, manifest = read("train.jsonl"), read("manifest.json")
    except Exception as exc:
        raise JobError(
            f"could not read the previous dataset from {repo_id}: {exc} — "
            "run with full_refresh to regenerate from scratch"
        ) from exc

    pairs: List[QAPair] = []
    for line in (train or "").splitlines():
        try:
            pair = QAPair.from_record(json.loads(line))
        except ValueError:
            pair = None
        if pair is not None:
            pairs.append(pair)

    sources: Dict[str, str] = {}
    if manifest:
        try:
            raw = json.loads(manifest).get("sources", {})
            sources = {k: v for k, v in raw.items() if isinstance(v, str)}
        except (ValueError, AttributeError):
            logger.warning(
                "unreadable manifest.json — treating every source as changed"
            )
    logger.info(
        "previous version: %d pair(s), %d tracked source(s)", len(pairs), len(sources)
    )
    return PreviousState(pairs, sources)


@dataclass
class _Source:
    key: str
    text: str
    changed: bool = True


@dataclass
class _Task:
    """One LLM call to make: a changed overview, or a batch of changed docs."""

    repo: RepoData
    label: str
    docs: Optional[List[RepoDoc]] = None
    avoid: List[str] = field(default_factory=list)
    focus: List[str] = field(default_factory=list)
    keys: List[str] = field(default_factory=list)
    failed: bool = False


def _chunks(texts: Sequence[str]) -> List[str]:
    chunks: List[str] = []
    for text in texts:
        chunks += split_sections(text) or ([text] if text.strip() else [])
    return chunks


def _grounding_for(
    embedder: Embedder, pairs: List[QAPair], sources: Dict[str, _Source]
) -> List[float]:
    """Each pair's answer ↔ closest chunk of its own sources' current text."""
    by_text: Dict[Tuple[str, ...], Any] = {}
    scores: List[float] = []
    answers = embedder.embed([p.answer for p in pairs]) if pairs else []
    for pair, answer_vector in zip(pairs, answers):
        keys = tuple(k for k in pair.sources if k in sources)
        if keys not in by_text:
            chunks = _chunks([sources[k].text for k in keys])
            by_text[keys] = embedder.embed(chunks) if chunks else []
        score = grounding_scores(answer_vector, by_text[keys])[0]
        scores.append(round(float(score), 3))
    return scores


def _plan_tasks(
    repos: List[RepoData],
    docs_by_repo: Dict[str, List[RepoDoc]],
    sources: Dict[str, _Source],
    index: SemanticIndex,
    embedder: Optional[Embedder],
) -> List[_Task]:
    """LLM calls for changed sources, each with its avoid/focus lists.

    Blocking (embeddings) — run in a worker thread.
    """
    tasks: List[_Task] = []
    for repo in repos:
        key = source_key(repo.name, "overview")
        if sources[key].changed:
            tasks.append(_Task(repo, "overview", keys=[key]))
        changed_docs = [
            d
            for d in docs_by_repo.get(repo.name, [])
            if sources[source_key(repo.name, d.path)].changed
        ]
        for i in range(0, len(changed_docs), DOCS_BATCH_SIZE):
            batch = changed_docs[i : i + DOCS_BATCH_SIZE]
            tasks.append(
                _Task(
                    repo,
                    f"docs {i // DOCS_BATCH_SIZE + 1}",
                    docs=batch,
                    keys=[source_key(repo.name, d.path) for d in batch],
                )
            )

    if embedder is None or not len(index):
        return tasks
    for task in tasks:
        text = (
            overview_context(task.repo)
            if task.docs is None
            else docs_batch_context(task.docs)[0]
        )
        sections = _chunks([text])
        if not sections:
            continue
        vectors = embedder.embed(sections)
        task.avoid = nearest_texts(
            vectors, index, MAX_AVOID_QUESTIONS, AVOID_MIN_SIMILARITY
        )
        uncovered = uncovered_sections(
            sections, vectors, index, config.uncovered_section_threshold
        )
        # All sections uncovered says nothing the plain prompt doesn't.
        if len(uncovered) < len(sections):
            task.focus = uncovered[:MAX_FOCUS_SECTIONS]
    return tasks


def _legacy_sources(pair: QAPair, sources: Dict[str, _Source]) -> List[str]:
    """Sources of a pair published before pairs recorded them."""
    if pair.category == "overview":
        return [source_key(pair.repo or "", "overview")]
    prefix = source_key(pair.repo or "", "")
    return [k for k in sources if k.startswith(prefix) and not k.endswith("::overview")]


async def build_qa_dataset(
    client: CorpusGitHubClient,
    snapshot: GitHubSnapshot,
    complete: CompletionFn,
    model: str,
    max_repos: Optional[int] = None,
    *,
    previous: Optional[PreviousState] = None,
    embedder: Optional[Embedder] = None,
    on_progress: Optional[ProgressFn] = None,
) -> QADataset:
    """Build the next version of the dataset from ``previous`` (empty = full run).

    1. Hash every source; an unchanged one keeps its pairs, with no LLM call.
       Pairs of repos gone from GitHub, or of docs removed from a repo, are
       dropped; repos outside this run's ``max_repos`` are carried over as-is.
    2. A changed source's old pairs are re-checked against its new text (kept
       when still grounded, else sent to review), then it is regenerated with
       the nearest existing questions as "don't ask again" and its uncovered
       sections as "prioritize".
    3. New pairs are deduplicated — normalized text, then embedding cosine
       against every kept pair — and held out for review when their answer is
       far from the source.

    Steps 2–3's embedding parts are skipped without an ``embedder``.
    ``on_progress(done, total, label)`` is called as each repo is generated.
    """
    previous = previous or PreviousState()
    # Every public repo with something to say (a description or a README),
    # most-starred first — ``max_repos`` only trims that for a cheap test run.
    repos = sorted(
        (r for r in snapshot.repos if r.description or r.readme),
        key=lambda r: r.stars,
        reverse=True,
    )[:max_repos]
    processed = {r.name for r in repos}
    live = {r.name for r in snapshot.repos}
    errors: List[str] = []

    async def docs_for(repo: RepoData) -> List[RepoDoc]:
        return await fetch_repo_docs(
            client,
            snapshot.username,
            repo.name,
            limit=MAX_DOCS_PER_REPO,
            max_chars=MAX_DOC_CHARS,
        )

    fetched = await gather_limited(REPO_CONCURRENCY, [docs_for(r) for r in repos])
    docs_by_repo = {repo.name: docs for repo, docs in zip(repos, fetched)}

    sources: Dict[str, _Source] = {}
    for repo in repos:
        key = source_key(repo.name, "overview")
        sources[key] = _Source(key, overview_context(repo))
        for doc in docs_by_repo[repo.name]:
            key = source_key(repo.name, doc.path)
            sources[key] = _Source(key, doc.content)
    for src in sources.values():
        src.changed = previous.sources.get(src.key) != content_hash(src.text)

    # Previous pairs: carried over, re-checked, or dropped.
    kept: List[QAPair] = []
    recheck: List[QAPair] = []
    for pair in previous.pairs:
        if pair.category == "profile" or pair.repo not in live:
            continue
        if pair.repo not in processed:
            kept.append(pair)
            continue
        keys = [
            k for k in (pair.sources or _legacy_sources(pair, sources)) if k in sources
        ]
        if not keys:
            continue
        pair.sources = keys
        (recheck if any(sources[k].changed for k in keys) else kept).append(pair)

    profile = profile_pairs(snapshot.profile, len(snapshot.repos))
    review: List[QAPair] = []

    def prepare() -> Tuple[SemanticIndex, List[_Task]]:
        if embedder is not None and recheck:
            for pair, score in zip(recheck, _grounding_for(embedder, recheck, sources)):
                pair.grounding = score
                if score >= config.answer_grounding_threshold:
                    kept.append(pair)
                else:
                    review.append(pair)
        else:
            kept.extend(recheck)
        index = SemanticIndex()
        if embedder is not None:
            questions = [p.question for p in profile + kept]
            if questions:
                index.add(questions, embedder.embed(questions))
        return index, _plan_tasks(repos, docs_by_repo, sources, index, embedder)

    carried = len(kept)
    index, tasks = await asyncio.to_thread(prepare)
    logger.info(
        "%d source(s) changed of %d; %d pair(s) carried over, %d re-checked "
        "(%d to review), %d LLM call(s) to make",
        sum(s.changed for s in sources.values()),
        len(sources),
        carried,
        len(recheck),
        len(review),
        len(tasks),
    )

    tasks_by_repo: Dict[str, List[_Task]] = {}
    for task in tasks:
        tasks_by_repo.setdefault(task.repo.name, []).append(task)
    done = 0
    if on_progress is not None:
        on_progress(0, len(tasks_by_repo), "")

    async def for_repo(repo_tasks: List[_Task]) -> List[QAPair]:
        nonlocal done
        pairs: List[QAPair] = []
        for task in repo_tasks:
            try:
                if task.docs is None:
                    pairs += await overview_pairs(
                        complete, model, task.repo, task.avoid, task.focus
                    )
                else:
                    pairs += await docs_batch_pairs(
                        complete, model, task.repo, task.docs, task.avoid, task.focus
                    )
            except JobError as exc:
                task.failed = True
                errors.append(f"{task.repo.name} ({task.label}): {exc}")
        done += 1
        logger.info("  [%d/%d] %s", done, len(tasks_by_repo), repo_tasks[0].repo.name)
        if on_progress is not None:
            on_progress(done, len(tasks_by_repo), repo_tasks[0].repo.name)
        return pairs

    generated: List[QAPair] = []
    for pairs in await gather_limited(
        REPO_CONCURRENCY, [for_repo(t) for t in tasks_by_repo.values()]
    ):
        generated += pairs

    # Existing pairs first, so a regenerated question never displaces one.
    clean, dropped = sanitize_pairs(profile + kept + generated)
    fresh_ids = {id(p) for p in generated}
    existing = [p for p in clean if id(p) not in fresh_ids]
    fresh = [p for p in clean if id(p) in fresh_ids]

    semantic_duplicates = 0

    def screen() -> List[QAPair]:
        nonlocal semantic_duplicates
        if embedder is None or not fresh:
            return fresh
        accepted: List[QAPair] = []
        vectors = embedder.embed([p.question for p in fresh])
        grounding = _grounding_for(embedder, fresh, sources)
        for pair, vector, score in zip(fresh, vectors, grounding):
            match = find_semantic_duplicate(
                vector, index, config.semantic_dedup_threshold
            )
            if match is not None:
                semantic_duplicates += 1
                logger.info(
                    "rephrasing (%.2f) of %r dropped: %r",
                    match[1],
                    index.texts[match[0]],
                    pair.question,
                )
                continue
            pair.grounding = score
            if score < config.answer_grounding_threshold:
                review.append(pair)
                logger.info(
                    "far from its source (%.2f), to review: %r", score, pair.question
                )
                continue
            index.add([pair.question], vector)
            accepted.append(pair)
        return accepted

    accepted = await asyncio.to_thread(screen)

    # A failed call's sources keep their previous hash (or none), so the next
    # run retries them instead of believing them up to date.
    failed = {k for t in tasks if t.failed for k in t.keys}
    manifest_sources = {
        k: v
        for k, v in previous.sources.items()
        if _source_repo(k) in live and _source_repo(k) not in processed
    }
    for key, src in sources.items():
        if key not in failed:
            manifest_sources[key] = content_hash(src.text)
        elif key in previous.sources:
            manifest_sources[key] = previous.sources[key]

    pairs = existing + accepted
    kept_count = sum(p.category != "profile" for p in existing)
    logger.info(
        "%d pair(s): %d kept, %d new; %d dropped, %d rephrasing(s), %d to review, "
        "%d error(s)",
        len(pairs),
        kept_count,
        len(accepted),
        dropped,
        semantic_duplicates,
        len(review),
        len(errors),
    )
    return QADataset(
        pairs,
        dropped,
        errors,
        kept=kept_count,
        new=len(accepted),
        semantic_duplicates=semantic_duplicates,
        review=review,
        manifest={
            "embedding_model": embedder.model_name if embedder else None,
            "sources": dict(sorted(manifest_sources.items())),
        },
        new_ids=[p.id for p in accepted if p.id],
    )


# --- Hugging Face export -----------------------------------------------------


def _size_category(n: int) -> str:
    if n < 1_000:
        return "n<1K"
    if n < 10_000:
        return "1K<n<10K"
    if n < 100_000:
        return "10K<n<100K"
    return "100K<n<1M"


def to_jsonl(pairs: List[QAPair]) -> str:
    ordered = sorted(pairs, key=lambda p: p.id or "")
    body = "\n".join(
        json.dumps(p.to_record(), ensure_ascii=False, separators=(",", ":"))
        for p in ordered
    )
    return body + "\n" if pairs else ""


def dataset_card(
    dataset: QADataset,
    username: str,
    license_id: str = "",
    license_link: str = "",
) -> str:
    pairs = dataset.pairs
    by_category = {c: 0 for c in CATEGORIES}
    repo_counts: Dict[str, int] = {}
    models: List[str] = []
    for p in pairs:
        by_category[p.category] = by_category.get(p.category, 0) + 1
        if p.repo:
            repo_counts[p.repo] = repo_counts.get(p.repo, 0) + 1
        if p.model and p.model not in models:
            models.append(p.model)
    repos = sorted(repo_counts.items(), key=lambda kv: kv[1], reverse=True)

    front = ["---", "language:", "- en"]
    if license_id:
        front.append(f"license: {license_id}")
        if license_id == "other" and license_link:
            front.append(f"license_link: {license_link}")
    front += [
        f'pretty_name: "GitHub Q&A — {username}"',
        "tags:",
        "- github",
        "- portfolio",
        "- synthetic",
        "annotations_creators:",
        "- machine-generated",
        "task_categories:",
        "- question-answering",
        "- text-generation",
        "size_categories:",
        f"- {_size_category(len(pairs))}",
        "---",
    ]

    repo_table = (
        "\n".join(
            f"| [{repo}](https://github.com/{username}/{repo}) | {n} |"
            for repo, n in repos
        )
        or "_none_"
    )
    dropped_note = (
        f" ({dataset.dropped} low-quality/duplicate pair(s) dropped before export)"
        if dataset.dropped
        else ""
    )
    model_list = ", ".join(f"`{m}`" for m in models) or "an LLM"
    embedding_model = dataset.manifest.get("embedding_model")
    semantic_note = (
        f" and by embedding similarity (`{embedding_model}`, "
        f"{dataset.semantic_duplicates} rephrasing(s) rejected this version)"
        if embedding_model
        else ""
    )
    review_note = (
        f"- {len(dataset.review)} pair(s) held out in `review.jsonl`: their answer "
        "is far from the source text (possible hallucination) — review before "
        "moving them into `train.jsonl`.\n"
        if dataset.review
        else ""
    )
    errors_section = ""
    if dataset.errors:
        errors_section = (
            f"\n## Known generation issues\n\n{len(dataset.errors)} non-fatal "
            "error(s) occurred while generating this dataset (the affected "
            "repo/batch was skipped, not the whole run):\n\n"
            + "\n".join(f"- {e}" for e in dataset.errors)
            + "\n"
        )

    body = f"""# GitHub Q&A dataset — {username}

Synthetic English question/answer pairs generated from the public GitHub profile and
repositories of [{username}](https://github.com/{username}) — profile facts, repo
READMEs, and `docs/` folders — for fine-tuning or evaluating a personal-assistant /
portfolio chatbot.

## Dataset structure

Each line of `train.jsonl` is one record:

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable id derived from the pair's content |
| `question` | string | Generated question, in English |
| `answer` | string | Generated answer, in English |
| `source` | string | Always `"github"` |
| `category` | string | `profile`, `overview` (repo description/README), or `docs` (repo `docs/` folder) |
| `repo` | string | Repository name the pair was derived from — absent for `profile` pairs |
| `model` | string | LLM that generated the pair — absent for `profile` pairs (deterministic, no LLM) |
| `confidence` | number | 0–1: how well the source supports the answer, as reported by the LLM; 1.0 for `profile` pairs — absent when the model gave none |
| `sources` | list | Source the pair was generated from (`<repo>::overview` or `<repo>::<doc path>`) — absent for `profile` pairs |
| `grounding` | number | Cosine similarity between the answer and the closest passage of its source — absent when not computed |

## Composition

- **{len(pairs)} pairs** total across **{len(repos)} repositories**{dropped_note}.
- {by_category["profile"]} from the GitHub profile (deterministic, no LLM), {by_category["overview"]} from repo
  descriptions/READMEs, {by_category["docs"]} from `docs/` folders.
- This version: {dataset.kept} pair(s) carried over from unchanged sources, {dataset.new} newly generated.
- Deduplicated by normalized question text{semantic_note}; trivial or self-answering pairs dropped.
{review_note}

### Pairs per repository

| Repository | Pairs |
|---|---|
{repo_table}

## Generation

- Profile pairs are extracted directly from the GitHub API — no LLM involved.
- Repository pairs are generated by {model_list}
  from each repo's description, README, and documentation.
- **Not manually reviewed** — treat this as synthetic/weak-labeled data and spot-check before
  relying on it for evaluation.
- Generated on {datetime.now(timezone.utc).isoformat()}.
{errors_section}"""
    return "\n".join(front) + "\n" + body


def publish_qa_dataset(dataset: QADataset, username: str, repo_id: str) -> dict:
    """Push ``train.jsonl``, ``review.jsonl``, ``manifest.json`` and ``README.md``
    to a private dataset in one commit — the manifest is what the next run
    diffs against, so it must never land without the pairs it describes."""
    from huggingface_hub import CommitOperationAdd

    from server.services.huggingface import _api, ensure_private_dataset_repo

    if not dataset.pairs:
        raise JobError("generated 0 pairs — refusing to publish an empty dataset")

    api = _api()
    ensure_private_dataset_repo(api, repo_id)
    card = dataset_card(
        dataset,
        username,
        _env("HF_QA_DATASET_LICENSE"),
        _env("HF_QA_DATASET_LICENSE_LINK"),
    )
    api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=[
            CommitOperationAdd("train.jsonl", to_jsonl(dataset.pairs).encode("utf-8")),
            # Rewritten every run (empty included) so a stale list never lingers.
            CommitOperationAdd(
                "review.jsonl", to_jsonl(dataset.review).encode("utf-8")
            ),
            CommitOperationAdd(
                "manifest.json",
                (json.dumps(dataset.manifest, indent=2) + "\n").encode("utf-8"),
            ),
            CommitOperationAdd("README.md", card.encode("utf-8")),
        ],
        commit_message=f"Export GitHub Q&A dataset ({len(dataset.pairs)} pairs)",
    )
    return {
        "repo": repo_id,
        "url": f"https://huggingface.co/datasets/{repo_id}",
        "records": len(dataset.pairs),
        "dropped": dataset.dropped,
    }


# --- CLI ---------------------------------------------------------------------


@dataclass
class Draft:
    """A generated, not yet published version of the dataset."""

    dataset: QADataset
    username: str
    repo_id: str
    full_refresh: bool
    model_ref: str

    def stats(self) -> Dict[str, Any]:
        return {
            "records": len(self.dataset.pairs),
            "dropped": self.dataset.dropped,
            "errors": self.dataset.errors,
            "kept": self.dataset.kept,
            "new": self.dataset.new,
            "semantic_duplicates": self.dataset.semantic_duplicates,
            "review": len(self.dataset.review),
            "full_refresh": self.full_refresh,
            "model": self.model_ref,
        }


async def generate(
    complete: Optional[CompletionFn] = None,
    max_repos: Optional[int] = None,
    full_refresh: Optional[bool] = None,
    model_ref: Optional[str] = None,
    require_hub: bool = True,
    on_progress: Optional[ProgressFn] = None,
) -> Draft:
    """Generate the next version of the Q&A dataset, without publishing it.

    Every public (non-fork, non-archived) repo is processed; ``max_repos``
    caps that to the most-starred ones — only useful for a cheap test run.
    The weekly cost stays bounded by the incremental mode: an unchanged repo
    costs no LLM call.

    The run is incremental against the published version (see
    :func:`build_qa_dataset`) whenever HF credentials are set. With
    ``require_hub`` (the default), HF_TOKEN/HF_QA_DATASET_REPO are required and
    the token is checked *before* any (limited) subscription usage is spent.
    ``full_refresh`` (default: env ``QA_FULL_REFRESH``) ignores the published
    version. ``model_ref`` picks the model (default: ``QA_JOB_MODEL``, else
    ``claude:$CLAUDE_MODEL``).
    """
    if full_refresh is None:
        full_refresh = _env("QA_FULL_REFRESH", "false").lower() in ("1", "true", "yes")
    username = _env("GITHUB_USERNAME")
    if not username:
        raise JobError("GITHUB_USERNAME is required")
    model_ref = model_ref or config.qa_job_model
    provider_name, model = parse_ref(model_ref)
    try:
        provider = get_provider(provider_name)
    except ProviderError as exc:
        raise JobError(str(exc)) from exc
    if complete is None and not provider.configured():
        raise JobError(
            f"{' or '.join(provider.missing_env())} is required to run {model_ref}"
        )

    repo_id = _env("HF_QA_DATASET_REPO")
    if require_hub:
        if not _env("HF_TOKEN"):
            raise JobError("HF_TOKEN is required")
        if not repo_id:
            raise JobError("HF_QA_DATASET_REPO is required (e.g. 'kevindb/github-qa')")

        from server.services.huggingface import _api

        try:
            await asyncio.to_thread(_api().whoami)
        except Exception as exc:
            raise JobError(f"HF_TOKEN rejected by Hugging Face: {exc}") from exc

    previous = PreviousState()
    if full_refresh:
        logger.info("full refresh: ignoring the previously published version")
    elif repo_id and _env("HF_TOKEN"):
        from server.services.huggingface import _api

        previous = await asyncio.to_thread(load_previous_state, _api(), repo_id)
    embedder = await asyncio.to_thread(get_local_embedder)

    complete = complete or provider_completion(model_ref)
    client = CorpusGitHubClient(_env("GITHUB_TOKEN") or None)
    try:
        logger.info("fetching GitHub snapshot for %s…", username)
        snapshot, fetch_errors = await fetch_snapshot(client, username)
        for err in fetch_errors:
            logger.warning("non-fatal: %s", err)

        logger.info("generating Q&A pairs with %s…", model)
        dataset = await build_qa_dataset(
            client,
            snapshot,
            complete,
            model,
            max_repos,
            previous=previous,
            embedder=embedder,
            on_progress=on_progress,
        )
    finally:
        await client.close()
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)
    return Draft(dataset, username, repo_id, full_refresh, model_ref)


async def publish(draft: Draft) -> dict:
    """Publish a draft to its Hugging Face repo (see :func:`publish_qa_dataset`)."""
    if not draft.repo_id:
        raise JobError("HF_QA_DATASET_REPO is required (e.g. 'kevindb/github-qa')")
    return await asyncio.to_thread(
        publish_qa_dataset, draft.dataset, draft.username, draft.repo_id
    )


async def run(
    complete: Optional[CompletionFn] = None,
    max_repos: Optional[int] = None,
    dry_run: bool = False,
    full_refresh: Optional[bool] = None,
    model_ref: Optional[str] = None,
) -> dict:
    """Generate the Q&A dataset and, unless ``dry_run``, publish it — the CLI
    and CI path, in one go. A dry run needs no HF_TOKEN/HF_QA_DATASET_REPO;
    without them it can't read the published version, so it is a full run."""
    draft = await generate(
        complete,
        max_repos=max_repos,
        full_refresh=full_refresh,
        model_ref=model_ref,
        require_hub=not dry_run,
    )
    if dry_run:
        return {"repo": draft.repo_id, "url": None, **draft.stats(), "dry_run": True}
    result = await publish(draft)
    return {**result, **draft.stats(), "dry_run": False}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = asyncio.run(run())
    except JobError as exc:
        print(f"qa_dataset: {exc}", file=sys.stderr)
        return 1
    logger.info(
        "done — %d pairs (%d kept, %d new; %d dropped, %d rephrasings, "
        "%d to review) at %s",
        result["records"],
        result["kept"],
        result["new"],
        result["dropped"],
        result["semantic_duplicates"],
        result["review"],
        result["url"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
