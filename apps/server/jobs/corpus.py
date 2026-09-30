"""Portfolio knowledge corpus → private Hugging Face dataset.

Two steps, kept separate so each needs only its own credentials:

    python -m server.jobs.corpus export --out DIR [--sources profile,github,...]
    python -m server.jobs.corpus push --dir DIR

``export`` reads the GitHub API only (GITHUB_USERNAME, GITHUB_TOKEN); ``push``
commits the directory to HF_DATASET_REPO in one commit (HF_TOKEN), so every
commit is a complete, self-consistent snapshot the portfolio can reindex from.

Ported from portfolio-next (``scripts/export-dataset.ts``,
``scripts/push-hf-dataset.ts``, ``src/lib/rag/{chunks,github-code,github-docs,
dataset}.ts``). Chunk ids and text layout are part of the contract with the
portfolio's Qdrant ingest — changing either re-embeds or duplicates the corpus.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from server.core.config import _env
from server.jobs.github_snapshot import (
    CorpusGitHubClient,
    GitHubAPIError,
    GitHubProfile,
    GitHubSnapshot,
    RepoData,
    RepoDoc,
    deterministic_id,
    fetch_repo_docs,
    fetch_snapshot,
    gather_limited,
    split_slug,
)

logger = logging.getLogger(__name__)

GENERATOR_NAME = "dataset-generator/server.jobs.corpus"
KNOWN_SOURCES = ("profile", "github", "github_code", "github_docs")

# Refuse to publish an implausibly small split: the ingest side clean-replaces
# each partition, so a truncated build (e.g. rate-limited) would overwrite a
# good corpus on the Hub and, at the next reindex, in Qdrant.
MIN_RECORDS = {"profile": 3, "github": 2, "github_code": 20, "github_docs": 3}

SPLIT_FILES = {name: f"data/{name}.jsonl" for name in KNOWN_SOURCES}


class JobError(RuntimeError):
    pass


@dataclass
class Chunk:
    id: str
    content: str
    source: str
    type: str
    repo: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    language: Optional[str] = None

    def to_record(self) -> dict:
        rec = {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "type": self.type,
        }
        for key in ("repo", "url", "path", "language"):
            value = getattr(self, key)
            if value:
                rec[key] = value
        return rec


# --- profile / github splits -------------------------------------------------


def _line(parts: List[str], label: str, value) -> None:
    if value not in (None, ""):
        parts.append(f"{label}: {value}")


def build_github_profile_chunks(p: GitHubProfile) -> List[Chunk]:
    overview = [f"GitHub Profile: {p.login}"]
    _line(overview, "Name", p.name)
    _line(overview, "Bio", p.bio)
    _line(overview, "Company", p.company)
    _line(overview, "Location", p.location)
    overview.append(f"GitHub URL: {p.html_url}")
    overview.append(f"Public repositories: {p.public_repos}")
    overview.append(f"Followers: {p.followers} | Following: {p.following}")

    contact: List[str] = []
    _line(contact, "Email", p.email)
    _line(contact, "Website/Blog", p.blog)
    if p.twitter:
        contact.append(f"Twitter: @{p.twitter}")
    contact.append(f"GitHub: {p.html_url}")

    return [
        Chunk(
            id=deterministic_id(f"github:profile:overview:{p.login}"),
            content="\n".join(overview).strip(),
            source="github",
            type="bio",
            url=p.html_url,
        ),
        Chunk(
            id=deterministic_id(f"github:profile:contact:{p.login}"),
            content=f"Contact information for {p.login}:\n" + "\n".join(contact),
            source="github",
            type="contact",
            url=p.html_url,
        ),
    ]


def build_github_repo_chunk(d: RepoData) -> Chunk:
    parts = [f"GitHub Repository: {d.name}"]
    _line(parts, "Description", d.description)
    _line(parts, "Primary Language", d.language)
    if d.topics:
        parts.append(f"Topics: {', '.join(d.topics)}")
    if d.stars > 0:
        parts.append(f"Stars: {d.stars}")
    _line(parts, "Homepage", d.homepage)
    _line(parts, "URL", d.url)

    content = "\n".join(parts)
    if d.readme:
        content += f"\n\nREADME:\n{d.readme}"
    return Chunk(
        id=deterministic_id(f"github:repo:{d.url}"),
        content=content.strip(),
        source="github",
        type="readme",
        repo=d.url,
        url=d.url,
    )


def build_github_snapshot_chunks(snap: GitHubSnapshot) -> List[Chunk]:
    chunks: List[Chunk] = []
    if snap.profile:
        chunks.extend(build_github_profile_chunks(snap.profile))
    chunks.extend(build_github_repo_chunk(r) for r in snap.repos)
    return chunks


def build_knowledge_profile_chunks(snap: GitHubSnapshot) -> List[Chunk]:
    """The ``profile`` split: bio overview, derived skills, one chunk per project."""
    chunks: List[Chunk] = []
    p = snap.profile
    name = (p.name if p else "") or "the portfolio owner"

    if p and p.name:
        overview = [f"Portfolio owner: {p.name}"]
        _line(overview, "Location", p.location)
        _line(overview, "Website", p.blog)
        overview.append(f"GitHub: https://github.com/{p.login}")
        _line(overview, "Bio", p.bio.strip())
        chunks.append(
            Chunk(
                id=deterministic_id("profile:overview"),
                content="\n".join(overview),
                source="profile",
                type="bio",
            )
        )

    techs = set()
    for repo in snap.repos:
        if repo.language:
            techs.add(repo.language)
        techs.update(t.strip() for t in repo.topics if t.strip())
    if techs:
        chunks.append(
            Chunk(
                id=deterministic_id("profile:derived_skills"),
                content=(
                    f"Technologies and programming languages used by {name} "
                    f"across their projects: {', '.join(sorted(techs))}"
                ),
                source="profile",
                type="skills",
            )
        )

    for repo in snap.repos:
        if not repo.name.strip():
            continue
        parts = [f"Project: {repo.name}"]
        _line(parts, "Description", repo.description)
        technologies = [t for t in [repo.language, *repo.topics] if t]
        if technologies:
            parts.append(f"Technologies: {', '.join(technologies)}")
        if repo.url:
            parts.append(f"GitHub: {repo.url}")
        if repo.homepage:
            parts.append(f"URL: {repo.homepage}")
        parts.append("Status: active")
        chunks.append(
            Chunk(
                id=deterministic_id(f"profile:project:{repo.name}"),
                content="\n".join(parts),
                source="profile",
                type="project",
                repo=repo.url,
                url=repo.homepage or None,
            )
        )
    return chunks


# --- github_code split -------------------------------------------------------

MAX_FILE_BYTES = 100 * 1024
MAX_CODE_CHUNK_CHARS = 2500
SPLIT_LINES = 150
MAX_FILE_CONCURRENT = 10

LANGUAGE_MAP = {
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".py": "Python",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".hpp": "C++",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".sh": "Shell",
    ".bash": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".rb": "Ruby",
    ".php": "PHP",
    ".tf": "Terraform",
    ".proto": "Protobuf",
    ".toml": "TOML",
    ".dockerfile": "Dockerfile",
}

# docs/ has its own split (github_docs); indexing it here too would make the
# same prose compete with itself for the retrieval budget.
SKIP_DIR_PREFIXES = (
    "docs/",
    "vendor/",
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    "__pycache__/",
    ".next/",
    ".nuxt/",
    "coverage/",
    ".nyc_output/",
    "target/",
    "out/",
    "bin/",
    ".bin/",
    ".cache/",
    "tmp/",
)

SKIP_EXTENSIONS = {
    ".lock",
    ".sum",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".pb",
    ".map",
    ".min",
}

_JS_FUNC = re.compile(r"^(export\s+)?(default\s+)?(async\s+)?(function|class)\s")
FUNC_PATTERNS = {
    "Go": re.compile(r"^func "),
    "TypeScript": _JS_FUNC,
    "JavaScript": _JS_FUNC,
    "Python": re.compile(r"^(def |class )"),
    "Rust": re.compile(
        r"^(pub(\s*\([^)]*\))?\s+)?(async\s+)?fn |^(pub\s+)?struct |^(pub\s+)?impl "
    ),
    "Ruby": re.compile(r"^(def |class |module )"),
    "PHP": re.compile(r"^(public|protected|private|static|function)\s"),
}


def _base(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _ext(path: str) -> str:
    base = _base(path)
    dot = base.rfind(".")
    return base[dot:].lower() if dot > 0 else ""


def is_code_indexable(path: str, size: int) -> bool:
    if size > MAX_FILE_BYTES:
        return False
    for prefix in SKIP_DIR_PREFIXES:
        if path.startswith(prefix) or f"/{prefix}" in path:
            return False
    if _base(path).startswith("."):
        return False
    return _ext(path) not in SKIP_EXTENSIONS


def language_for_path(path: str) -> str:
    base = _base(path)
    if base == "Dockerfile" or base.startswith("Dockerfile."):
        return "Dockerfile"
    return LANGUAGE_MAP.get(_ext(path), "")


@dataclass
class RawFile:
    repo: str
    path: str
    language: str
    content: str
    url: str


def _split_points(lines: List[str], language: str) -> List[int]:
    pattern = FUNC_PATTERNS.get(language)
    points = []
    for i in range(1, len(lines)):
        if lines[i - 1] == "" and pattern and pattern.match(lines[i]):
            points.append(i)
            continue
        if i % 120 == 0:
            points.append(i)
    points.append(len(lines))
    return points


def _code_content(f: RawFile, lines: List[str], start: int, end: int) -> str:
    result = f"// File: {f.path} ({f.language}) lines {start}-{end}\n" + "\n".join(
        lines
    )
    if len(result) > MAX_CODE_CHUNK_CHARS:
        return f"{result[:MAX_CODE_CHUNK_CHARS]}\n// [truncated]"
    return result


def _code_chunk(f: RawFile, owner: str, content: str, start: int, end: int) -> Chunk:
    return Chunk(
        id=deterministic_id(f"github_code:{owner}/{f.repo}:{f.path}:{start}"),
        content=content,
        source="github_code",
        type="code",
        repo=f.repo,
        url=f"{f.url}#L{start}-L{end}",
        path=f.path,
        language=f.language,
    )


def chunk_file(f: RawFile, owner: str) -> List[Chunk]:
    """Whole file up to SPLIT_LINES, else split on function/class boundaries
    (falling back to every 120 lines)."""
    lines = f.content.split("\n")
    if len(lines) <= SPLIT_LINES:
        content = _code_content(f, lines, 1, len(lines))
        return (
            [_code_chunk(f, owner, content, 1, len(lines))] if content.strip() else []
        )

    chunks: List[Chunk] = []
    start = 0
    for end in _split_points(lines, f.language):
        if end <= start:
            continue
        content = _code_content(f, lines[start:end], start + 1, end)
        if content.strip():
            chunks.append(_code_chunk(f, owner, content, start + 1, end))
        start = end
    return chunks


async def _fetch_repo_files(
    client: CorpusGitHubClient, owner: str, repo: str
) -> List[RawFile]:
    branch = await client.default_branch(owner, repo)
    tree = await client.repo_tree(owner, repo, branch)
    candidates = [
        e
        for e in tree
        if e.get("type") == "blob"
        and is_code_indexable(e.get("path", ""), e.get("size") or 0)
        and language_for_path(e.get("path", ""))
    ]

    async def fetch(entry: dict) -> Optional[RawFile]:
        path = entry["path"]
        try:
            content = await client.file_content(owner, repo, path)
        except (GitHubAPIError, httpx.HTTPError):
            return None
        return RawFile(
            repo=repo,
            path=path,
            language=language_for_path(path),
            content=content,
            url=f"https://github.com/{owner}/{repo}/blob/{branch}/{path}",
        )

    results = await gather_limited(MAX_FILE_CONCURRENT, [fetch(c) for c in candidates])
    return [r for r in results if r is not None]


async def build_github_code_chunks(
    client: CorpusGitHubClient, owner: str, slugs: Sequence[str]
) -> Tuple[List[Chunk], List[str]]:
    chunks: List[Chunk] = []
    errors: List[str] = []
    for slug in slugs:
        repo_owner, repo_name = split_slug(slug, owner)
        try:
            for f in await _fetch_repo_files(client, repo_owner, repo_name):
                chunks.extend(chunk_file(f, repo_owner))
        except (GitHubAPIError, httpx.HTTPError) as exc:
            errors.append(f"{slug}: {exc}")
    return chunks, errors


# --- github_docs split -------------------------------------------------------

MAX_INDEXED_DOCS_PER_REPO = 25
MAX_DOC_CHUNK_CHARS = 2000
MIN_SECTION_CHARS = 80

_FENCE = re.compile(r"^\s*```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Section:
    heading: str
    body: str


def split_markdown_sections(text: str) -> List[Section]:
    """Split markdown on headings, keeping the trail of parent headings so a
    chunk still says what it is about once pulled out of its file."""
    sections: List[Section] = []
    trail: List[str] = []
    heading = ""
    body: List[str] = []
    fenced = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append(Section(heading, content))
        body.clear()

    for line in text.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            del trail[max(0, min(len(trail), level - 1)) :]
            while len(trail) < level - 1:
                trail.append("")
            trail.append(match.group(2).strip())
            heading = " > ".join(t for t in trail if t)
            continue
        body.append(line)
    flush()
    return sections


def _cap_section(section: Section) -> List[Section]:
    if len(section.body) <= MAX_DOC_CHUNK_CHARS:
        return [section]
    parts: List[Section] = []
    buffer = ""
    for paragraph in re.split(r"\n{2,}", section.body):
        if buffer and len(buffer) + len(paragraph) > MAX_DOC_CHUNK_CHARS:
            parts.append(Section(section.heading, buffer.strip()))
            buffer = ""
        buffer += f"{paragraph}\n\n"
    if buffer.strip():
        parts.append(Section(section.heading, buffer.strip()))
    return parts


def _merge_short_sections(sections: List[Section]) -> List[Section]:
    merged: List[Section] = []
    for section in sections:
        if (
            merged
            and len(merged[-1].body) < MIN_SECTION_CHARS
            and len(merged[-1].body) + len(section.body) <= MAX_DOC_CHUNK_CHARS
        ):
            prefix = f"{section.heading}\n" if section.heading else ""
            merged[-1].body = f"{merged[-1].body}\n\n{prefix}{section.body}"
            continue
        merged.append(Section(section.heading, section.body))
    return merged


def doc_sections(doc: RepoDoc) -> List[Section]:
    return [
        part
        for section in _merge_short_sections(split_markdown_sections(doc.content))
        for part in _cap_section(section)
    ]


def _doc_chunk(
    owner: str, repo: str, branch: str, doc: RepoDoc, section: Section, index: int
) -> Chunk:
    title = f"{doc.path} — {section.heading}" if section.heading else doc.path
    return Chunk(
        id=deterministic_id(f"github_docs:{owner}/{repo}:{doc.path}:{index}"),
        content=f"# {title}\n\n{section.body}",
        source="github_docs",
        type="docs",
        repo=repo,
        url=f"https://github.com/{owner}/{repo}/blob/{branch}/{doc.path}",
        path=doc.path,
        language="Markdown",
    )


async def build_github_docs_chunks(
    client: CorpusGitHubClient, owner: str, slugs: Sequence[str]
) -> Tuple[List[Chunk], List[str]]:
    chunks: List[Chunk] = []
    errors: List[str] = []
    for slug in slugs:
        repo_owner, repo_name = split_slug(slug, owner)
        try:
            docs = await fetch_repo_docs(
                client, repo_owner, repo_name, limit=MAX_INDEXED_DOCS_PER_REPO
            )
            if not docs:
                continue
            branch = await client.default_branch(repo_owner, repo_name)
            for doc in docs:
                for i, section in enumerate(doc_sections(doc)):
                    chunks.append(
                        _doc_chunk(repo_owner, repo_name, branch, doc, section, i)
                    )
        except (GitHubAPIError, httpx.HTTPError) as exc:
            errors.append(f"{slug}: {exc}")
    return chunks, errors


# --- serialisation -----------------------------------------------------------


def _dumps(obj) -> str:
    # Compact, non-ASCII kept: byte-identical to the TS exporter's
    # JSON.stringify, so the first Python-built commit only diffs real changes.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_jsonl(chunks: List[Chunk]) -> str:
    """Records sorted by id, so an unchanged corpus re-exports byte-identical."""
    ordered = sorted(chunks, key=lambda c: c.id)
    body = "\n".join(_dumps(c.to_record()) for c in ordered)
    return body + "\n" if chunks else ""


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def dataset_card(manifest: dict, repo: str, username: str) -> str:
    lines = [
        "---",
        "license: other",
        "language:",
        "  - en",
        "  - fr",
        "tags:",
        "  - portfolio",
        "  - rag",
        "  - knowledge-base",
        "configs:",
    ]
    for f in manifest["files"]:
        lines.append(f"  - config_name: {f['source']}")
        lines.append("    data_files:")
        lines.append(f"      - split: train\n        path: {f['path']}")
    lines += ["---", ""]
    lines += ["# Portfolio knowledge base", ""]
    lines.append(
        f"Retrieval corpus powering the chat agent on "
        f"[{username}](https://github.com/{username})'s portfolio."
    )
    lines += [
        "Generated automatically — **do not edit by hand**, changes are "
        "overwritten on the next run.",
        "",
    ]
    lines += ["## Splits", "", "| Config | File | Records |", "|---|---|---|"]
    for f in manifest["files"]:
        lines.append(f"| `{f['source']}` | `{f['path']}` | {f['records']} |")
    lines += [
        "",
        "## Schema",
        "",
        "One JSON object per line:",
        "",
        "| Field | Description |",
        "|---|---|",
        "| `id` | Deterministic UUIDv5 — stable across runs for unchanged content |",
        "| `content` | The text passed to the model as context |",
        "| `source` | Partition: `profile`, `github`, `github_code`, `github_docs` |",
        "| `type` | `bio`, `skills`, `project`, `experience`, `education`, "
        "`contact`, `readme`, `code`, `docs`, … |",
        "| `repo` | Repository name, when applicable |",
        "| `url` | Source URL; for code, a permalink with a line anchor |",
        "| `path` | File path within the repository (`github_code`, `github_docs`) |",
        "| `language` | Programming language (`github_code`); `Markdown` for "
        "`github_docs` |",
        "",
        "Records are sorted by `id`, so a week-to-week diff shows only what "
        "actually changed.",
        "No embedding vectors are stored: the corpus stays independent of "
        "whichever embedding model indexes it.",
        "",
        "## Provenance",
        "",
        f"- Generated at: `{manifest['generated_at']}`",
        f"- Generator: `{manifest['generator']}`",
    ]
    if manifest.get("source_commit"):
        lines.append(f"- Source commit: `{manifest['source_commit']}`")
    if repo:
        lines.append(f"- Repository: `{repo}`")
    lines += [
        "",
        "Each commit is a complete, self-consistent snapshot: re-ingesting an "
        "earlier revision restores that week's corpus exactly.",
    ]
    return "\n".join(lines) + "\n"


# --- export ------------------------------------------------------------------


def parse_sources(raw: str) -> List[str]:
    requested = [s.strip() for s in raw.split(",") if s.strip()]
    if not requested:
        raise JobError("--sources must name at least one source")
    unknown = [s for s in requested if s not in KNOWN_SOURCES]
    if unknown:
        raise JobError(
            f'unknown source "{unknown[0]}"; known sources: {", ".join(KNOWN_SOURCES)}'
        )
    return requested


async def export_corpus(
    out: Path,
    sources: List[str],
    username: str,
    token: Optional[str],
    hf_repo: str = "",
) -> dict:
    """Build every requested split under ``out`` and return the manifest."""
    (out / "data").mkdir(parents=True, exist_ok=True)
    client = CorpusGitHubClient(token)
    snapshot: Optional[GitHubSnapshot] = None
    slugs: Optional[List[str]] = None

    async def github_snapshot() -> GitHubSnapshot:
        nonlocal snapshot
        if snapshot is None:
            snapshot, errors = await fetch_snapshot(client, username)
            for err in errors:
                logger.warning("non-fatal: %s", err)
        return snapshot

    async def repo_slugs() -> List[str]:
        nonlocal slugs
        if slugs is None:
            slugs = await client.list_user_repos(username)
        return slugs

    manifest: dict = {
        "generated_at": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "generator": GENERATOR_NAME,
    }
    commit = _git_commit()
    if commit:
        manifest["source_commit"] = commit
    files: List[Dict] = []

    try:
        for name in sources:
            logger.info("export: building source %s", name)
            errors: List[str] = []
            if name == "profile":
                chunks = build_knowledge_profile_chunks(await github_snapshot())
                if not chunks:
                    raise JobError(
                        "build profile: github sync populated nothing — the GitHub "
                        "API was unreachable or rate-limited"
                    )
            elif name == "github":
                chunks = build_github_snapshot_chunks(await github_snapshot())
            elif name == "github_docs":
                chunks, errors = await build_github_docs_chunks(
                    client, username, await repo_slugs()
                )
            else:
                chunks, errors = await build_github_code_chunks(
                    client, username, await repo_slugs()
                )
            for err in errors:
                logger.warning("non-fatal: %s", err)

            if len(chunks) < MIN_RECORDS[name]:
                raise JobError(
                    f'source "{name}" produced only {len(chunks)} chunks (expected '
                    f"at least {MIN_RECORDS[name]}); refusing to publish a "
                    "truncated dataset"
                )

            jsonl = write_jsonl(chunks)
            path = SPLIT_FILES[name]
            (out / path).write_text(jsonl, encoding="utf-8")
            files.append(
                {
                    "path": path,
                    "source": name,
                    "records": len(chunks),
                    "sha256": hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
                }
            )
            logger.info("export: wrote %s (%d records)", path, len(chunks))
    finally:
        await client.close()

    manifest["files"] = sorted(files, key=lambda f: f["path"])
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(
        dataset_card(manifest, hf_repo, username), encoding="utf-8"
    )
    return manifest


# --- push --------------------------------------------------------------------


def push_corpus(directory: Path, repo_id: str, commit_sha: str = "") -> str:
    """Commit the exported directory to a private HF dataset in one commit."""
    from server.services.huggingface import (
        HuggingFaceNotConfiguredError,
        _api,
        ensure_private_dataset_repo,
        qualify_repo_id,
    )

    if not directory.is_dir():
        raise JobError(f"{directory} does not exist — run the export first")
    manifest_path = directory / "manifest.json"
    # The manifest is what the ingest side reads to discover the splits.
    if not manifest_path.is_file():
        raise JobError(f"no manifest.json in {directory} — the export did not complete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    api = _api()
    # Fail on a bad token before uploading megabytes: a fine-grained token
    # missing write access otherwise only surfaces at the final commit.
    try:
        username = api.whoami().get("name")
    except Exception as exc:
        raise JobError(f"HF_TOKEN rejected by Hugging Face: {exc}") from exc
    try:
        # A bare name would 404 on commit — complete it with the namespace.
        repo_id = qualify_repo_id(repo_id)
    except HuggingFaceNotConfiguredError as exc:
        raise JobError(str(exc)) from exc
    ensure_private_dataset_repo(api, repo_id)

    files = manifest.get("files") or []
    total = sum(f.get("records", 0) for f in files)
    sha = commit_sha or manifest.get("source_commit") or ""
    title = "Weekly corpus refresh" + (f" ({sha[:7]})" if sha else "")
    description = "\n".join(
        [
            f"{total} records across {len(files)} splits.",
            *(f"- {f['source']}: {f['records']} records ({f['path']})" for f in files),
            f"\nGenerated from {GENERATOR_NAME}@{sha}" if sha else "",
        ]
    )

    logger.info("uploading %s to %s as %s", directory, repo_id, username)
    api.upload_folder(
        folder_path=str(directory),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=title,
        commit_description=description,
    )
    return f"https://huggingface.co/datasets/{repo_id}"


# --- CLI ---------------------------------------------------------------------


def _required(name: str) -> str:
    value = _env(name)
    if not value:
        raise JobError(f"{name} is required")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.jobs.corpus")
    sub = parser.add_subparsers(dest="command", required=True)
    export_p = sub.add_parser("export", help="build the corpus from the GitHub API")
    export_p.add_argument("--out", default="./dist/dataset")
    export_p.add_argument("--sources", default=",".join(KNOWN_SOURCES))
    push_p = sub.add_parser("push", help="commit an exported corpus to the Hub")
    push_p.add_argument("--dir", default="./dist/dataset")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "export":
            sources = parse_sources(args.sources)
            username = _required("GITHUB_USERNAME")
            token = _env("GITHUB_TOKEN") or None
            if not token:
                logger.warning(
                    "GITHUB_TOKEN is not set — 60 unauthenticated requests/hour "
                    "is not enough for a code export"
                )
            manifest = asyncio.run(
                export_corpus(
                    Path(args.out), sources, username, token, _env("HF_DATASET_REPO")
                )
            )
            logger.info(
                "export: complete (%s, %d splits)", args.out, len(manifest["files"])
            )
        else:
            _required("HF_TOKEN")
            url = push_corpus(
                Path(args.dir),
                _required("HF_DATASET_REPO"),
                os.getenv("GITHUB_SHA", ""),
            )
            logger.info("done — %s", url)
    except JobError as exc:
        print(f"corpus: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
