"""GitHub Q&A dataset → private Hugging Face dataset.

Run by the ``github-personal`` and ``github-recipe`` jobs (jobs/registry.py),
both started from the GitHub page: :func:`generate` (or
:func:`generate_from_recipe`) stops at a draft, :func:`publish` pushes it once
reviewed.

Profile facts become pairs deterministically; each notable repo gets one
"overview" LLM call (description + README) plus one call per small batch of
its ``docs/`` files. The result is deduplicated and pushed to the Q&A dataset
repo as ``train.jsonl`` + a dataset card — the file the portfolio's
"Synchroniser les paires Q/R" action ingests.

Generation goes through the model provider registry (services/providers), on
the OpenAI-compatible endpoint: the model picked on the GitHub page, else your
LLM (Models page), else OPENAI_LLM_MODEL.

Ported from portfolio-next (``scripts/generate-and-export-qa-dataset.ts``,
``src/lib/rag/github-qa.ts``, ``src/lib/rag/github-hf-export.ts``).
"""

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from server.core.config import _env, config
from server.core.cpu import cpu_bound
from server.services.credentials import GITHUB_TOKEN, HF_TOKEN, Credentials
import httpx

from server.jobs.github_snapshot import (
    CorpusGitHubClient,
    GitHubAPIError,
    GitHubProfile,
    GitHubSnapshot,
    RepoData,
    RepoDoc,
    fetch_docs_by_path,
    fetch_repo_docs,
    fetch_snapshot,
    gather_limited,
)
from server.jobs.tech_stack import (
    canonical,
    format_stack_entries,
    main_entries,
    rank_stack,
    repo_technologies,
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
    get_embedder,
    grounding_scores,
    nearest_texts,
    split_sections,
    thresholds_of,
    uncovered_sections,
)

logger = logging.getLogger(__name__)

REPO_CONCURRENCY = 3
BASE_PAIRS_PER_REPO = 4
DOCS_BATCH_SIZE = 3
PAIRS_PER_DOC = 2
DOCS_BATCH_CHAR_BUDGET = 6000
# A repo with a docs/ folder used to get up to 8 files x 2 pairs, so a few
# well-documented repos held most of the dataset while a repo with only a
# README had three pairs. Capping the docs keeps a visitor's "what is X?" about
# equally well covered whichever repo X is.
MAX_DOCS_PER_REPO = 6
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

CATEGORIES = ("profile", "overview", "docs", "repo")
# Pairs built from GitHub data alone: rebuilt every run, never carried over.
DETERMINISTIC_CATEGORIES = ("profile", "repo")


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


def _token_budget(pairs: int) -> int:
    return min(1500, 400 + pairs * 150)


MAX_PROFILE_STACK_LANGUAGES = 4
MAX_PROFILE_STACK_TOOLS = 8
MAX_PROFILE_PROJECTS = 8


def profile_pairs(
    profile: Optional[GitHubProfile],
    repo_count: int,
    repos: Sequence[RepoData] = (),
) -> List[QAPair]:
    """Deterministic pairs about the person, from GitHub data alone.

    These are what visitors ask first — stack, projects, how to get in touch —
    and no repo's README answers them, so they can't be left to the per-repo
    LLM calls.
    """
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

    contact = [
        f"by email at {profile.email}" if profile.email else "",
        f"through their website {profile.blog}" if profile.blog else "",
        f"on GitHub at {profile.html_url}" if profile.html_url else "",
    ]
    contact = [c for c in contact if c]
    if contact:
        pairs.append(
            pair(f"How can I contact {who}?", f"You can reach {who} {_join(contact)}.")
        )

    # Follower counts used to be a pair here: they change weekly and no visitor
    # asks for them, so they only churned the dataset.
    stack = rank_stack(list(repos))
    if stack.languages or stack.tools:
        languages = format_stack_entries(
            main_entries(stack.languages, MAX_PROFILE_STACK_LANGUAGES)
        )
        tools = format_stack_entries(main_entries(stack.tools, MAX_PROFILE_STACK_TOOLS))
        n = stack.total_projects
        answer = (
            f"Across their {n} public project{'s' if n > 1 else ''}, {who} mostly uses "
        )
        if languages and tools:
            answer += f"{languages}, together with {tools}."
        else:
            answer += f"{languages or tools}."
        pairs.append(pair(f"What is {who}'s main tech stack?", answer))

    described = sorted(
        (r for r in repos if r.description.strip()),
        key=lambda r: (-r.stars, r.name.lower()),
    )[:MAX_PROFILE_PROJECTS]
    if described:
        pairs.append(
            pair(
                f"What kind of projects has {who} built?",
                "; ".join(
                    f"{r.name}: {r.description.strip().rstrip('.')}" for r in described
                )
                + ".",
            )
        )
    return pairs


def repo_pairs(repo: RepoData) -> List[QAPair]:
    """Deterministic pairs about one repo, from its GitHub metadata.

    "What is X?", "what is X built with?" and "where is X?" are the first things
    a visitor asks about any project, and they should be answerable whatever the
    size of X's README or docs — the LLM pairs cover the depth, these cover the
    floor. Exact facts rather than model output, so confidence is 1.0.
    """
    name = repo.name.strip()
    if not name:
        return []

    def pair(question: str, answer: str) -> QAPair:
        return QAPair(
            question=question,
            answer=answer,
            category="repo",
            repo=name,
            confidence=1.0,
        )

    pairs: List[QAPair] = []
    if repo.description.strip():
        pairs.append(pair(f"What is {name}?", repo.description.strip()))

    techs = repo_technologies(repo)
    if techs:
        language = canonical(repo.language) if repo.language else ""
        others = [t for t in techs if t != language]
        if language and others:
            answer = f"{name} is written in {language} and uses {_join(others)}."
        elif language:
            answer = f"{name} is written in {language}."
        else:
            answer = f"{name} uses {_join(others)}."
        pairs.append(pair(f"What technologies does {name} use?", answer))

    if repo.url:
        answer = f"{name}'s source code is on GitHub at {repo.url}"
        if repo.homepage:
            answer += f", and its website is {repo.homepage}"
        pairs.append(pair(f"Where can I find {name}?", answer + "."))
    return pairs


def _join(items: List[str]) -> str:
    """``a``, ``a or b``, ``a, b or c``."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


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


def _system_prompt(subject: str, focus: str) -> str:
    return (
        "You generate question/answer pairs in English for a fine-tuning dataset, "
        f"from {subject}. {JSON_FORMAT_INSTRUCTION} Answers must stay factual and "
        f"rely only on the given context. {ANSWER_STYLE} {focus}"
    )


def _name_the_repo(repo: str) -> str:
    """Each pair is retrieved alone, out of its repo's context: a question
    saying "this project" matches nothing and can't be attributed. Most
    generated questions used to read that way."""
    return (
        f'\n\nEvery question must name the repository "{repo}" explicitly '
        f'(e.g. "What does {repo} use for …?") — never "this project", "the '
        'repository" or "it".'
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
    if repo.technologies:
        parts.append(
            "Technologies (from its dependency manifests): "
            + ", ".join(repo.technologies)
        )
    if repo.readme:
        # The whole README (already capped at MAX_README_CHARS): a short one is
        # all the material a small repo has, and cutting it at 1500 left the
        # LLM with half of the big ones too.
        parts.append(f"README:\n{repo.readme}")
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
                f"from this context:\n\n{context}"
                + _name_the_repo(repo.name)
                + _guidance(avoid, focus)
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
                "summarizing the whole file in a single question. Prefer what a "
                "visitor evaluating the project would ask — what it does, how it "
                "is designed, which notable choices it makes — over minor "
                "settings such as a font name or a single default value.",
            ),
            user=(
                f"Repository: {repo.name}\n\nGenerate {want} distinct "
                f"question/answer pairs from this documentation:\n\n"
                + context
                + _name_the_repo(repo.name)
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
class Selection:
    """What a dataset recipe feeds the generation, instead of everything.

    ``overview_repos`` are the repos whose README and metadata are a source
    (their overview call, their deterministic repo pairs); ``docs_by_repo``
    holds the ``docs/`` files to generate from, already read.
    """

    include_profile: bool = True
    overview_repos: Set[str] = field(default_factory=set)
    docs_by_repo: Dict[str, List[RepoDoc]] = field(default_factory=dict)
    # Selected repos that couldn't be read this time: their published pairs
    # are carried over as they are, not dropped for a transient failure.
    carry_over: Set[str] = field(default_factory=set)


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
    for pair, answer_vector in zip(pairs, answers, strict=True):
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
        # A recipe may leave a repo's README out: then it has no overview.
        if key in sources and sources[key].changed:
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
        task.avoid, task.focus = guidance_for(text, index, embedder)
    return tasks


def _legacy_sources(pair: QAPair, sources: Dict[str, _Source]) -> List[str]:
    """Sources of a pair published before pairs recorded them."""
    if pair.category == "overview":
        return [source_key(pair.repo or "", "overview")]
    prefix = source_key(pair.repo or "", "")
    return [k for k in sources if k.startswith(prefix) and not k.endswith("::overview")]


def recheck_pairs(
    embedder: Optional[Embedder],
    recheck: List[QAPair],
    sources: Dict[str, _Source],
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
    sources: Dict[str, _Source],
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
    sources: Dict[str, "_Source"],
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

    await gather_limited(REPO_CONCURRENCY, [grade(k, g) for k, g in groups.items()])
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
    selection: Optional[Selection] = None,
    grader: Optional[CompletionFn] = None,
) -> QADataset:
    """Build the next version of the dataset from ``previous`` (empty = full run).

    Without a ``selection`` every repo with a description or a README is
    processed, with its default ``docs/`` pick and the profile facts; with one
    (a dataset recipe), exactly what it selects. Either way, previous pairs of
    a source outside this run are dropped.

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
    # A recipe's repos are all taken: one may feed the dataset by its docs only.
    repos = sorted(
        (
            r
            for r in snapshot.repos
            if selection is not None or r.description or r.readme
        ),
        key=lambda r: r.stars,
        reverse=True,
    )[:max_repos]
    processed = {r.name for r in repos}
    live = {r.name for r in snapshot.repos} | (
        selection.carry_over if selection is not None else set()
    )
    errors: List[str] = []

    async def docs_for(repo: RepoData) -> List[RepoDoc]:
        return await fetch_repo_docs(
            client,
            snapshot.username,
            repo.name,
            limit=MAX_DOCS_PER_REPO,
            max_chars=MAX_DOC_CHARS,
        )

    if selection is None:
        fetched = await gather_limited(REPO_CONCURRENCY, [docs_for(r) for r in repos])
        docs_by_repo = {
            repo.name: docs for repo, docs in zip(repos, fetched, strict=True)
        }
    else:
        docs_by_repo = {r.name: selection.docs_by_repo.get(r.name, []) for r in repos}

    def has_overview(repo: RepoData) -> bool:
        return selection is None or repo.name in selection.overview_repos

    sources: Dict[str, _Source] = {}
    for repo in repos:
        if has_overview(repo):
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
        if pair.category in DETERMINISTIC_CATEGORIES or pair.repo not in live:
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

    # Deterministic pairs go first in the sanitize pass and into the semantic
    # index, so an LLM rephrasing of "What is X?" is dropped as a duplicate.
    profile = (
        profile_pairs(snapshot.profile, len(snapshot.repos), snapshot.repos)
        if selection is None or selection.include_profile
        else []
    )
    profile += [
        p for repo in snapshot.repos if has_overview(repo) for p in repo_pairs(repo)
    ]
    review: List[QAPair] = []

    def prepare() -> Tuple[SemanticIndex, List[_Task]]:
        recheck_pairs(embedder, recheck, sources, kept, review)
        index = question_index(embedder, profile + kept)
        return index, _plan_tasks(repos, docs_by_repo, sources, index, embedder)

    carried = len(kept)
    index, tasks = await cpu_bound(prepare)  # embedding batches: core/cpu.py
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

    accepted, semantic_duplicates = await cpu_bound(  # embedding batches: core/cpu.py
        screen_pairs, embedder, fresh, sources, index, review, errors
    )
    if grader is not None:
        accepted = await grade_pairs(grader, accepted, sources, review, errors)

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
    kept_count = sum(p.category not in DETERMINISTIC_CATEGORIES for p in existing)
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
            "embedding_checks": embedding_checks(embedder, fresh, recheck),
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
| `category` | string | `profile` (the person), `repo` (a repo's description, stack and links), `overview` (repo README), or `docs` (repo `docs/` folder) |
| `repo` | string | Repository name the pair was derived from — absent for `profile` pairs |
| `model` | string | LLM that generated the pair — absent for `profile` and `repo` pairs (deterministic, no LLM) |
| `confidence` | number | 0–1: how well the source supports the answer, as reported by the LLM; 1.0 for `profile` and `repo` pairs — absent when the model gave none |
| `sources` | list | Source the pair was generated from (`<repo>::overview` or `<repo>::<doc path>`) — absent for `profile` and `repo` pairs |
| `grounding` | number | Cosine similarity between the answer and the closest passage of its source — absent when not computed |
| `judge` | number | The LLM's grade of the pair, 0–1 (true to its source, useful, self-contained); below 0.6 the pair is held out in `review.jsonl` — absent when not graded |
| `judge_note` | string | The grade's reason, in a few words |

## Composition

- **{len(pairs)} pairs** total across **{len(repos)} repositories**{dropped_note}.
- {by_category["profile"]} from the GitHub profile and {by_category["repo"]} from repo metadata (description,
  stack, links; both deterministic, no LLM), {by_category["overview"]} from repo READMEs,
  {by_category["docs"]} from `docs/` folders.
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


def publish_qa_dataset(
    creds: Credentials,
    dataset: QADataset,
    username: str,
    repo_id: str,
    *,
    card: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> dict:
    """Push ``train.jsonl``, ``review.jsonl``, ``manifest.json`` and ``README.md``
    to a private dataset in one commit — the manifest is what the next run
    diffs against, so it must never land without the pairs it describes.
    ``card`` replaces the GitHub dataset card (another job's dataset)."""
    from huggingface_hub import CommitOperationAdd

    from server.services.huggingface import (
        HuggingFaceNotConfiguredError,
        _api,
        ensure_private_dataset_repo,
        qualify_repo_id,
    )

    if not dataset.pairs:
        raise JobError("generated 0 pairs — refusing to publish an empty dataset")

    api = _api(creds)
    try:
        # A bare "github-qa" would 404 on commit — complete it with the namespace
        # (also fixes drafts stored before this was done at generation time).
        repo_id = qualify_repo_id(creds, repo_id)
    except HuggingFaceNotConfiguredError as exc:
        raise JobError(str(exc)) from exc
    ensure_private_dataset_repo(api, repo_id)
    if card is None:
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
        commit_message=commit_message
        or f"Export GitHub Q&A dataset ({len(dataset.pairs)} pairs)",
    )
    return {
        "repo": repo_id,
        "url": f"https://huggingface.co/datasets/{repo_id}",
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


def _model_for(
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


async def generate(
    creds: Credentials,
    complete: Optional[CompletionFn] = None,
    max_repos: Optional[int] = None,
    full_refresh: bool = False,
    model_ref: Optional[str] = None,
    on_progress: Optional[ProgressFn] = None,
) -> Draft:
    """Generate the next version of the Q&A dataset, without publishing it.

    Every public (non-fork, non-archived) repo is processed; ``max_repos``
    caps that to the most-starred ones — only useful for a cheap test run.
    The cost stays bounded by the incremental mode: an unchanged repo costs
    no LLM call.

    The run is incremental against the published version (see
    :func:`build_qa_dataset`): the Hugging Face token and the Q&A dataset repo
    are required, and the token is checked *before* any (limited) subscription
    usage is spent. ``full_refresh`` ignores the published version.
    ``model_ref`` picks the model (default: ``OPENAI_LLM_MODEL``).
    """
    username = creds.github_username
    if not username:
        raise JobError("Your GitHub username is required (set it in Settings)")
    model_ref, model = _model_for(creds, model_ref, complete)

    repo_id = creds.hf_qa_repo
    if not creds.has(HF_TOKEN):
        raise JobError("Your Hugging Face token is required (add it in Settings)")
    if not repo_id:
        raise JobError(
            "The Q&A dataset repo is required in Settings (e.g. 'kevindb/github-qa')"
        )

    from server.services.huggingface import (
        HuggingFaceNotConfiguredError,
        _api,
        qualify_repo_id,
    )

    try:
        await asyncio.to_thread(_api(creds).whoami)
    except Exception as exc:
        raise JobError(f"Hugging Face rejected your token: {exc}") from exc
    try:
        repo_id = await asyncio.to_thread(qualify_repo_id, creds, repo_id)
    except HuggingFaceNotConfiguredError as exc:
        raise JobError(str(exc)) from exc

    previous = PreviousState()
    if full_refresh:
        logger.info("full refresh: ignoring the previously published version")
    else:
        previous = await asyncio.to_thread(load_previous_state, _api(creds), repo_id)
    embedder = await asyncio.to_thread(get_embedder, creds)

    complete = complete or provider_completion(model_ref, creds)
    client = CorpusGitHubClient(creds.secret(GITHUB_TOKEN) or None)
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
            grader=complete,
        )
    finally:
        await client.close()
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)
    dataset.removed = removed_pairs(previous, dataset)
    return Draft(dataset, username, repo_id, full_refresh, model_ref)


async def generate_from_recipe(
    creds: Credentials,
    recipe: Dict[str, Any],
    *,
    full_refresh: bool = False,
    model_ref: Optional[str] = None,
    complete: Optional[CompletionFn] = None,
    on_progress: Optional[ProgressFn] = None,
) -> Draft:
    """The next version of a recipe's dataset, without publishing it.

    Like :func:`generate`, on what the recipe selects (services/recipes.py):
    its repos — each with its README and metadata or not, and its chosen
    ``docs/`` files (``None``: the default pick) — and the profile facts or
    not, incrementally against the recipe's target repo. The Hugging Face
    token is checked before any model usage is spent.
    """
    username = creds.github_username
    if not username:
        raise JobError("Your GitHub username is required (set it in Settings)")
    chosen = [s for s in recipe.get("sources") or [] if isinstance(s, dict)]
    include_profile = bool(recipe.get("include_profile", True))
    if not chosen and not include_profile:
        raise JobError("This recipe selects nothing: add a repo or the profile facts")
    model_ref, model = _model_for(creds, model_ref, complete)

    if not creds.has(HF_TOKEN):
        raise JobError("Your Hugging Face token is required (add it in Settings)")
    from server.services.huggingface import (
        HuggingFaceNotConfiguredError,
        _api,
        qualify_repo_id,
    )

    try:
        await asyncio.to_thread(_api(creds).whoami)
    except Exception as exc:
        raise JobError(f"Hugging Face rejected your token: {exc}") from exc
    try:
        repo_id = await asyncio.to_thread(
            qualify_repo_id, creds, str(recipe["target_repo"])
        )
    except HuggingFaceNotConfiguredError as exc:
        raise JobError(str(exc)) from exc

    if full_refresh:
        logger.info("full refresh: ignoring the previously published version")
        previous = PreviousState()
    else:
        previous = await asyncio.to_thread(load_previous_state, _api(creds), repo_id)
    embedder = await asyncio.to_thread(get_embedder, creds)
    complete = complete or provider_completion(model_ref, creds)

    client = CorpusGitHubClient(creds.secret(GITHUB_TOKEN) or None)

    async def read(
        source: Dict[str, Any],
    ) -> Tuple[Optional[RepoData], List[RepoDoc], List[str]]:
        name = str(source.get("repo") or "")
        try:
            repo = await client.fetch_repo(username, name)
        except (GitHubAPIError, httpx.HTTPError) as exc:
            return None, [], [f"{name}: {exc}"]
        docs = source.get("docs")
        if docs is None:
            found = await fetch_repo_docs(
                client,
                username,
                repo.name,
                limit=MAX_DOCS_PER_REPO,
                max_chars=MAX_DOC_CHARS,
            )
            return repo, found, []
        found, errors = await fetch_docs_by_path(
            client, username, repo.name, list(docs), MAX_DOC_CHARS
        )
        return repo, found, errors

    try:
        profile = await client.fetch_profile(username) if include_profile else None
        results = await gather_limited(REPO_CONCURRENCY, [read(s) for s in chosen])
        published = {p.repo.lower(): p.repo for p in previous.pairs if p.repo}
        selection = Selection(include_profile=include_profile)
        repos: List[RepoData] = []
        errors: List[str] = []
        for source, (repo, docs, problems) in zip(chosen, results, strict=True):
            errors += problems
            if repo is None:
                name = str(source.get("repo") or "")
                selection.carry_over.add(published.get(name.lower(), name))
                continue
            repos.append(repo)
            selection.docs_by_repo[repo.name] = docs
            if source.get("readme", True):
                selection.overview_repos.add(repo.name)
        snapshot = GitHubSnapshot(
            username=username,
            profile=profile,
            repos=repos,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            "recipe %r: %d repo(s), profile %s, generating with %s…",
            recipe.get("name"),
            len(repos),
            "on" if include_profile else "off",
            model,
        )
        dataset = await build_qa_dataset(
            client,
            snapshot,
            complete,
            model,
            previous=previous,
            embedder=embedder,
            on_progress=on_progress,
            selection=selection,
            grader=complete,
        )
    finally:
        await client.close()
    dataset.errors = errors + dataset.errors
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)
    dataset.removed = removed_pairs(previous, dataset)
    return Draft(dataset, username, repo_id, full_refresh, model_ref)


async def publish(creds: Credentials, draft: Draft) -> dict:
    """Publish a draft to its Hugging Face repo (see :func:`publish_qa_dataset`)."""
    if not draft.repo_id:
        raise JobError(
            "The Q&A dataset repo is required in Settings (e.g. 'kevindb/github-qa')"
        )
    return await asyncio.to_thread(
        publish_qa_dataset, creds, draft.dataset, draft.username, draft.repo_id
    )
