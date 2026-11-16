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
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from server.core.config import _env
from server.services.credentials import GITHUB_TOKEN, Credentials
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
from server.services.semantic import (
    Embedder,
)
from server.jobs.qa_build import (
    Run,
    generate_draft,
    SourcePlan,
    Task,
    TaskGroup,
    build,
    ANSWER_STYLE,
    CompletionFn,
    CompletionRequest,
    Draft,
    JSON_FORMAT_INSTRUCTION,
    JobError,
    PreviousState,
    ProgressFn,
    QADataset,
    QAPair,
    Source,
    guidance,
    size_category,
    token_budget,
    foreign_note,
    generate_pairs,
    publish_dataset,
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


CATEGORIES = ("profile", "overview", "docs", "repo")


# Pairs built from GitHub data alone: rebuilt every run, never carried over.
DETERMINISTIC_CATEGORIES = ("profile", "repo")


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
                + guidance(avoid, focus)
            ),
            max_tokens=token_budget(BASE_PAIRS_PER_REPO),
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
                + guidance(avoid, focus)
            ),
            max_tokens=token_budget(want),
        ),
        repo.name,
        "docs",
        model,
    )
    for pair in pairs:
        pair.sources = [source_key(repo.name, doc.path) for doc in included]
    return pairs


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


def own_github_pair(row: Dict[str, Any]) -> Optional[QAPair]:
    """The row as a GitHub Q&A pair, when it is one: a pair in one of the
    job's categories. Anything else is a foreign row, published back as it is."""
    pair = QAPair.from_record(row)
    return pair if pair is not None and pair.category in CATEGORIES else None


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


def _legacy_sources(pair: QAPair, sources: Dict[str, Source]) -> List[str]:
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

    sources: Dict[str, Source] = {}
    for repo in repos:
        if has_overview(repo):
            key = source_key(repo.name, "overview")
            sources[key] = Source(key, overview_context(repo))
        for doc in docs_by_repo[repo.name]:
            key = source_key(repo.name, doc.path)
            sources[key] = Source(key, doc.content)
    # Deterministic pairs: the profile facts, then each repo's.
    facts = (
        profile_pairs(snapshot.profile, len(snapshot.repos), snapshot.repos)
        if selection is None or selection.include_profile
        else []
    )
    facts += [
        p for repo in snapshot.repos if has_overview(repo) for p in repo_pairs(repo)
    ]

    def groups() -> List[TaskGroup]:
        """The calls for what changed: per repo, its overview, then its changed
        docs a few at a time."""
        out: List[TaskGroup] = []
        for repo in repos:
            tasks: List[Task] = []
            key = source_key(repo.name, "overview")
            # A recipe may leave a repo's README out: then it has no overview.
            if key in sources and sources[key].changed:

                async def overview(
                    avoid: List[str], focus: List[str], repo: RepoData = repo
                ) -> List[QAPair]:
                    return await overview_pairs(complete, model, repo, avoid, focus)

                tasks.append(
                    Task(
                        [key],
                        f"{repo.name} (overview)",
                        overview_context(repo),
                        overview,
                    )
                )
            changed_docs = [
                d
                for d in docs_by_repo.get(repo.name, [])
                if sources[source_key(repo.name, d.path)].changed
            ]
            for i in range(0, len(changed_docs), DOCS_BATCH_SIZE):
                batch = changed_docs[i : i + DOCS_BATCH_SIZE]

                async def docs(
                    avoid: List[str],
                    focus: List[str],
                    repo: RepoData = repo,
                    batch: List[RepoDoc] = batch,
                ) -> List[QAPair]:
                    return await docs_batch_pairs(
                        complete, model, repo, batch, avoid, focus
                    )

                tasks.append(
                    Task(
                        [source_key(repo.name, d.path) for d in batch],
                        f"{repo.name} (docs {i // DOCS_BATCH_SIZE + 1})",
                        docs_batch_context(batch)[0],
                        docs,
                    )
                )
            if tasks:
                out.append(TaskGroup(repo.name, tasks))
        return out

    def outside(repo: Optional[str]) -> bool:
        """A repo that still exists but is not part of this run."""
        return repo in live and repo not in processed

    plan = SourcePlan(
        sources=sources,
        facts=facts,
        groups=groups,
        # A fact is rebuilt, never carried; neither is a pair of a repo gone
        # from GitHub (its sources are not this run's).
        sources_of=lambda pair: (
            None
            if pair.category in DETERMINISTIC_CATEGORIES
            else (pair.sources or _legacy_sources(pair, sources))
        ),
        concurrency=REPO_CONCURRENCY,
        outside_pair=lambda pair: (
            pair.category not in DETERMINISTIC_CATEGORIES and outside(pair.repo)
        ),
        outside_source=lambda key: outside(_source_repo(key)),
    )
    result = await build(
        plan, previous, embedder=embedder, grader=grader, on_progress=on_progress
    )
    return QADataset(
        result.existing + result.accepted,
        result.dropped,
        result.errors,
        kept=result.kept,
        new=len(result.accepted),
        semantic_duplicates=result.semantic_duplicates,
        review=result.review,
        manifest=result.manifest(embedder),
        new_ids=[p.id for p in result.accepted if p.id],
    )


def dataset_card(
    dataset: QADataset,
    username: str,
    license_id: str = "",
    license_link: str = "",
    foreign: int = 0,
) -> str:
    """The GitHub Q&A dataset's README. ``foreign`` rows — the dataset's rows
    this job did not generate — count in its size, not in its statistics."""
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
        f"- {size_category(len(pairs) + foreign)}",
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
{foreign_note(foreign)}- Deduplicated by normalized question text{semantic_note}; trivial or self-answering pairs dropped.
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

    async def make(run: Run) -> Tuple[QADataset, str]:
        client = CorpusGitHubClient(creds.secret(GITHUB_TOKEN) or None)
        try:
            logger.info("fetching GitHub snapshot for %s…", username)
            snapshot, fetch_errors = await fetch_snapshot(client, username)
            for err in fetch_errors:
                logger.warning("non-fatal: %s", err)

            logger.info("generating Q&A pairs with %s…", run.model)
            dataset = await build_qa_dataset(
                client,
                snapshot,
                run.complete,
                run.model,
                max_repos,
                previous=run.previous,
                embedder=run.embedder,
                on_progress=on_progress,
                grader=run.complete,
            )
        finally:
            await client.close()
        return dataset, username

    return await generate_draft(
        creds,
        creds.hf_qa_repo or "",
        own_github_pair,
        make,
        missing_repo=(
            "The Q&A dataset repo is required in Settings (e.g. 'kevindb/github-qa')"
        ),
        full_refresh=full_refresh,
        model_ref=model_ref,
        complete=complete,
    )


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

    async def make(run: Run) -> Tuple[QADataset, str]:
        client = CorpusGitHubClient(creds.secret(GITHUB_TOKEN) or None)
        try:
            dataset = await _build_from_recipe(
                client, username, recipe, chosen, include_profile, run, on_progress
            )
        finally:
            await client.close()
        return dataset, username

    return await generate_draft(
        creds,
        str(recipe["target_repo"]),
        own_github_pair,
        make,
        missing_repo="This recipe names no dataset repo",
        full_refresh=full_refresh,
        model_ref=model_ref,
        complete=complete,
    )


async def _build_from_recipe(
    client: CorpusGitHubClient,
    username: str,
    recipe: Dict[str, Any],
    chosen: List[Dict[str, Any]],
    include_profile: bool,
    run: Run,
    on_progress: Optional[ProgressFn],
) -> QADataset:
    """Read what the recipe selects, then build its dataset."""
    previous, complete, model = run.previous, run.complete, run.model

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
        embedder=run.embedder,
        on_progress=on_progress,
        selection=selection,
        grader=complete,
    )
    dataset.errors = errors + dataset.errors
    return dataset


def publish_qa_dataset(
    creds: Credentials,
    dataset: QADataset,
    username: str,
    repo_id: str,
    *,
    base_commit: Optional[str] = None,
) -> dict:
    """Publish a GitHub Q&A dataset with its own card
    (:func:`server.jobs.qa_build.publish_dataset`)."""
    return publish_dataset(
        creds,
        dataset,
        repo_id,
        own=own_github_pair,
        card=lambda foreign: dataset_card(
            dataset,
            username,
            _env("HF_QA_DATASET_LICENSE"),
            _env("HF_QA_DATASET_LICENSE_LINK"),
            foreign=foreign,
        ),
        commit_message=f"Export GitHub Q&A dataset ({len(dataset.pairs)} pairs)",
        base_commit=base_commit,
    )


async def publish(creds: Credentials, draft: Draft) -> dict:
    """Publish a draft to its Hugging Face repo (see :func:`publish_qa_dataset`)."""
    if not draft.repo_id:
        raise JobError(
            "The Q&A dataset repo is required in Settings (e.g. 'kevindb/github-qa')"
        )
    return await asyncio.to_thread(
        publish_qa_dataset,
        creds,
        draft.dataset,
        draft.username,
        draft.repo_id,
        base_commit=draft.base_commit,
    )
