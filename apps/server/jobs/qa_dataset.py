"""GitHub Q&A dataset → private Hugging Face dataset.

    python -m server.jobs.qa_dataset

Profile facts become pairs deterministically; each notable repo gets one
"overview" LLM call (description + README) plus one call per small batch of
its ``docs/`` files. The result is deduplicated and pushed to
HF_QA_DATASET_REPO as ``train.jsonl`` + a dataset card — the file the
portfolio's "Synchroniser les paires Q/R" action ingests.

Generation goes through the Claude Agent SDK, authenticated with
CLAUDE_CODE_OAUTH_TOKEN (``claude setup-token``) so it bills against a Claude
Pro/Max subscription: that subscription grants no plain-API access, only
Claude Code, which is what the SDK drives. The SDK bundles the Claude Code
binary, so it lives in the optional ``jobs`` dependency group rather than the
server image (``uv sync --group jobs``).

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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from server.core.config import _env
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

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"

MAX_REPOS = 15
REPO_CONCURRENCY = 3
BASE_PAIRS_PER_REPO = 3
DOCS_BATCH_SIZE = 3
PAIRS_PER_DOC = 2
DOCS_BATCH_CHAR_BUDGET = 6000
MAX_DOCS_PER_REPO = 8
MAX_DOC_CHARS = 3000

ANSWER_STYLE = (
    "Keep answers concise (1 to 3 sentences max) and rephrase them in your own "
    "words — never copy a passage verbatim from the given context. Each pair must "
    "cover a different aspect: no rewording the same question in another form."
)
JSON_FORMAT_INSTRUCTION = (
    "Respond ONLY with a compact JSON array (no extra whitespace, indentation, or "
    "line breaks), no surrounding text, in the format "
    '[{"question":"...","answer":"..."}].'
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

    def to_record(self) -> dict:
        # Key order matches the TS exporter's records, keeping the Hub diff clean.
        rec: Dict[str, str] = {
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "category": self.category,
        }
        if self.repo:
            rec["repo"] = self.repo
        if self.model:
            rec["model"] = self.model
        if self.id:
            rec["id"] = self.id
        return rec


@dataclass
class CompletionRequest:
    system: str
    user: str
    max_tokens: int


CompletionFn = Callable[[CompletionRequest], Awaitable[str]]


def claude_completion(model: str) -> CompletionFn:
    """CompletionFn backed by the Claude Agent SDK.

    No tools and no filesystem settings: each call is a plain text generation,
    never picking up a CLAUDE.md or hooks from the runner's checkout. A failed
    query degrades to '' so the retry-on-empty logic handles it.
    """
    from claude_agent_sdk import (  # ty: ignore[unresolved-import]
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )

    async def complete(req: CompletionRequest) -> str:
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=req.system,
            allowed_tools=[],
            setting_sources=[],
            max_turns=1,
        )
        text = ""
        try:
            async for message in query(prompt=req.user, options=options):
                if (
                    isinstance(message, ResultMessage)
                    and message.subtype == "success"
                    and message.result
                ):
                    text = message.result
        except Exception as exc:
            logger.warning("claude query failed: %s", exc)
        return text

    return complete


def _token_budget(pairs: int) -> int:
    return min(1500, 400 + pairs * 150)


def profile_pairs(profile: Optional[GitHubProfile], repo_count: int) -> List[QAPair]:
    if not profile or not profile.login:
        return []
    who = profile.name or profile.login

    def pair(question: str, answer: str) -> QAPair:
        return QAPair(question=question, answer=answer, category="profile")

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
    )


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


async def overview_pairs(
    complete: CompletionFn, model: str, repo: RepoData
) -> List[QAPair]:
    parts = [f"Repository: {repo.name}"]
    if repo.description:
        parts.append(f"Description: {repo.description}")
    if repo.language:
        parts.append(f"Primary language: {repo.language}")
    if repo.topics:
        parts.append(f"Topics: {', '.join(repo.topics)}")
    if repo.readme:
        parts.append(f"README (excerpt):\n{repo.readme[:1500]}")
    context = "\n\n".join(parts)
    return await generate_pairs(
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
            ),
            max_tokens=_token_budget(BASE_PAIRS_PER_REPO),
        ),
        repo.name,
        "overview",
        model,
    )


async def docs_batch_pairs(
    complete: CompletionFn, model: str, repo: RepoData, batch: List[RepoDoc]
) -> List[QAPair]:
    used = 0
    parts: List[str] = []
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
        used += len(content)
    if not parts:
        return []

    want = len(batch) * PAIRS_PER_DOC
    return await generate_pairs(
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
                + "\n\n".join(parts)
            ),
            max_tokens=_token_budget(want),
        ),
        repo.name,
        "docs",
        model,
    )


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


async def build_qa_dataset(
    client: CorpusGitHubClient,
    snapshot: GitHubSnapshot,
    complete: CompletionFn,
    model: str,
) -> QADataset:
    repos = sorted(
        (r for r in snapshot.repos if r.description or r.readme),
        key=lambda r: r.stars,
        reverse=True,
    )[:MAX_REPOS]
    errors: List[str] = []
    done = 0

    async def for_repo(repo: RepoData) -> List[QAPair]:
        nonlocal done
        pairs: List[QAPair] = []
        try:
            pairs += await overview_pairs(complete, model, repo)
        except JobError as exc:
            errors.append(f"{repo.name} (overview): {exc}")

        docs = await fetch_repo_docs(
            client,
            snapshot.username,
            repo.name,
            limit=MAX_DOCS_PER_REPO,
            max_chars=MAX_DOC_CHARS,
        )
        for i in range(0, len(docs), DOCS_BATCH_SIZE):
            try:
                pairs += await docs_batch_pairs(
                    complete, model, repo, docs[i : i + DOCS_BATCH_SIZE]
                )
            except JobError as exc:
                errors.append(f"{repo.name} (docs {i // DOCS_BATCH_SIZE + 1}): {exc}")
        done += 1
        logger.info("  [%d/%d] %s", done, len(repos), repo.name)
        return pairs

    per_repo = await gather_limited(REPO_CONCURRENCY, [for_repo(r) for r in repos])
    raw = profile_pairs(snapshot.profile, len(snapshot.repos))
    for pairs in per_repo:
        raw += pairs
    clean, dropped = sanitize_pairs(raw)
    logger.info(
        "generated %d pair(s), %d dropped, %d error(s)", len(raw), dropped, len(errors)
    )
    return QADataset(clean, dropped, errors)


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

## Composition

- **{len(pairs)} pairs** total across **{len(repos)} repositories**{dropped_note}.
- {by_category["profile"]} from the GitHub profile (deterministic, no LLM), {by_category["overview"]} from repo
  descriptions/READMEs, {by_category["docs"]} from `docs/` folders.
- Deduplicated by normalized question text; trivial or self-answering pairs dropped.

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
    """Push ``train.jsonl`` + ``README.md`` to a private dataset in one commit."""
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


async def run(complete: Optional[CompletionFn] = None) -> dict:
    from server.services.huggingface import _api

    username = _env("GITHUB_USERNAME")
    if not username:
        raise JobError("GITHUB_USERNAME is required")
    if complete is None and not (
        _env("CLAUDE_CODE_OAUTH_TOKEN") or _env("ANTHROPIC_API_KEY")
    ):
        raise JobError("CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY) is required")
    if not _env("HF_TOKEN"):
        raise JobError("HF_TOKEN is required")
    repo_id = _env("HF_QA_DATASET_REPO")
    if not repo_id:
        raise JobError("HF_QA_DATASET_REPO is required (e.g. 'kevindb/github-qa')")

    # Check the HF token before spending any (limited) subscription usage.
    try:
        await asyncio.to_thread(_api().whoami)
    except Exception as exc:
        raise JobError(f"HF_TOKEN rejected by Hugging Face: {exc}") from exc

    model = _env("CLAUDE_MODEL", DEFAULT_MODEL)
    complete = complete or claude_completion(model)
    client = CorpusGitHubClient(_env("GITHUB_TOKEN") or None)
    try:
        logger.info("fetching GitHub snapshot for %s…", username)
        snapshot, fetch_errors = await fetch_snapshot(client, username)
        for err in fetch_errors:
            logger.warning("non-fatal: %s", err)

        logger.info("generating Q&A pairs with %s…", model)
        dataset = await build_qa_dataset(client, snapshot, complete, model)
    finally:
        await client.close()
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)

    return await asyncio.to_thread(publish_qa_dataset, dataset, username, repo_id)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = asyncio.run(run())
    except JobError as exc:
        print(f"qa_dataset: {exc}", file=sys.stderr)
        return 1
    logger.info(
        "done — %d pairs (%d dropped) at %s",
        result["records"],
        result["dropped"],
        result["url"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
