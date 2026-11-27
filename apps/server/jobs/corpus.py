"""Portfolio knowledge corpus → private Hugging Face dataset.

Two steps, which the ``knowledge-corpus`` job (jobs/registry.py, started from
the GitHub page) runs back to back: :func:`export_corpus` reads the GitHub API
only and writes every split to a directory; :func:`push_corpus` commits that
directory to the corpus repo in one commit, so every commit is a complete,
self-consistent snapshot the portfolio can reindex from.

Ported from portfolio-next (``scripts/export-dataset.ts``,
``scripts/push-hf-dataset.ts``, ``src/lib/rag/{chunks,github-code,github-docs,
dataset}.ts``). Chunk ids and text layout are part of the contract with the
portfolio's Qdrant ingest — changing either re-embeds or duplicates the corpus.
"""

import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx2

from server.core.config import config
from server.services.credentials import Credentials
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
from server.jobs.tech_stack import format_stack_entries, rank_stack, repo_technologies

logger = logging.getLogger(__name__)

GENERATOR_NAME = "dataset-generator/server.jobs.corpus"

# The corpus layout the manifest declares. 2: every record carries a
# ``content_hash``; READMEs are split into sections; code is split rather than
# truncated, keyed by its content, and ids no longer move when a file grows.
# A reader must refuse a version above the one it knows.
SCHEMA_VERSION = 2
KNOWN_SOURCES = ("profile", "github", "github_code", "github_docs")

# Refuse to publish an implausibly small split: the ingest side clean-replaces
# each partition, so a truncated build (e.g. rate-limited) would overwrite a
# good corpus on the Hub and, at the next reindex, in Qdrant.
MIN_RECORDS = {"profile": 3, "github": 2, "github_code": 20, "github_docs": 3}

SPLIT_FILES = {name: f"data/{name}.jsonl" for name in KNOWN_SOURCES}


class JobError(RuntimeError):
    pass


def content_hash(text: str) -> str:
    """SHA-256 of a chunk's text: what an indexer compares to skip re-embedding."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _occurrence_keys(keys: Sequence[str]) -> List[str]:
    """``keys`` made unique in order: the second ``k`` is ``k#1``, the third ``k#2``.

    A key alone stays as it is, so an id only depends on the chunks that share
    its key, never on how many other chunks come before it.
    """
    seen: Dict[str, int] = {}
    out: List[str] = []
    for key in keys:
        n = seen.get(key, 0)
        seen[key] = n + 1
        out.append(key if n == 0 else f"{key}#{n}")
    return out


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
        rec["content_hash"] = content_hash(self.content)
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


def _section_text(section: "Section") -> str:
    return f"# {section.heading}\n{section.body}" if section.heading else section.body


def build_github_repo_chunks(d: RepoData) -> List[Chunk]:
    """The repo's card, then one chunk per further README section.

    The card holds the metadata and the README's first section (its title and
    introduction), so "what is <repo>?" still finds one chunk that answers it.
    The rest of the README is cut like ``docs/`` (heading trail kept, short
    sections merged, long ones split at paragraphs) instead of being truncated
    at a character cap.
    """
    parts = [f"GitHub Repository: {d.name}"]
    _line(parts, "Description", d.description)
    _line(parts, "Primary Language", d.language)
    if d.topics:
        parts.append(f"Topics: {', '.join(d.topics)}")
    if d.stars > 0:
        parts.append(f"Stars: {d.stars}")
    _line(parts, "Homepage", d.homepage)
    _line(parts, "URL", d.url)

    readme = d.readme_full or d.readme
    sections = doc_sections(RepoDoc(path="README.md", content=readme)) if readme else []
    content = "\n".join(parts)
    if sections:
        content += f"\n\nREADME:\n{_section_text(sections[0])}"
    chunks = [
        Chunk(
            id=deterministic_id(f"github:repo:{d.url}"),
            content=content.strip(),
            source="github",
            type="readme",
            # The name, like every other split: the portfolio lists repos from
            # this field, and a URL here showed each repo twice in that list.
            repo=d.name,
            url=d.url,
        )
    ]
    rest = sections[1:]
    keys = _occurrence_keys([f"github:readme:{d.url}:{s.heading}" for s in rest])
    for key, section in zip(keys, rest, strict=True):
        title = (
            f"{d.name} README — {section.heading}"
            if section.heading
            else (f"{d.name} README")
        )
        chunks.append(
            Chunk(
                id=deterministic_id(key),
                content=f"# {title}\n\n{section.body}",
                source="github",
                type="readme",
                repo=d.name,
                url=d.url,
            )
        )
    return chunks


def build_github_snapshot_chunks(snap: GitHubSnapshot) -> List[Chunk]:
    chunks: List[Chunk] = []
    if snap.profile:
        chunks.extend(build_github_profile_chunks(snap.profile))
    for repo in snap.repos:
        chunks.extend(build_github_repo_chunks(repo))
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

    # Ranked rather than an alphabetical tag dump: "what is the main stack?"
    # needs to know what is used everywhere vs. once, which a flat list hides.
    stack = rank_stack(snap.repos)
    if stack.languages or stack.tools or stack.tooling:
        n = stack.total_projects
        lines = [
            f"Main technology stack of {name}, ranked by how many of their "
            f"{n} public project{'s' if n > 1 else ''} use each technology."
        ]
        if stack.languages:
            lines.append(
                f"Programming languages: {format_stack_entries(stack.languages)}"
            )
        if stack.tools:
            lines.append(
                f"Frameworks, tools and platforms: {format_stack_entries(stack.tools)}"
            )
        if stack.tooling:
            lines.append(
                "Development tooling (linting, testing, migrations): "
                f"{format_stack_entries(stack.tooling)}"
            )
        chunks.append(
            Chunk(
                id=deterministic_id("profile:derived_skills"),
                content="\n".join(lines),
                source="profile",
                type="skills",
            )
        )

    for repo in snap.repos:
        if not repo.name.strip():
            continue
        parts = [f"Project: {repo.name}"]
        _line(parts, "Description", repo.description)
        technologies = repo_technologies(repo)
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
                repo=repo.name,
                url=repo.homepage or None,
            )
        )
    return chunks


# --- github_code split -------------------------------------------------------

MAX_FILE_BYTES = 100 * 1024
MAX_CODE_CHUNK_CHARS = 2500
SPLIT_LINES = 150
WINDOW_LINES = 120
# A file with less code than this (``package main``, an empty ``__init__.py``)
# answers no question and only crowds the retrieval budget.
MIN_CODE_CHARS = 40
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


# Prose the github split already holds (README), or text that is not the
# project's knowledge: licences, changelogs, contributor lists. Only as prose
# files: `security.py` or `history.ts` is code like any other.
_BOILERPLATE_NAME = re.compile(
    r"^(readme|changelog|changes|history|license|licence|copying|notice|authors|"
    r"contributors|code_of_conduct|security)(\.(md|markdown|rst|txt|adoc))?$",
    re.IGNORECASE,
)
# Generated or vendored files: lockfiles the extension list misses, minified
# bundles, protobuf and snapshot output.
GENERATED_NAMES = {"package-lock.json", "pnpm-lock.yaml", "npm-shrinkwrap.json"}
GENERATED_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".bundle.js",
    ".pb.go",
    "_pb2.py",
    ".generated.ts",
    ".gen.go",
)


def is_boilerplate(path: str) -> bool:
    base = _base(path)
    lower = base.lower()
    return (
        bool(_BOILERPLATE_NAME.match(base))
        or lower in GENERATED_NAMES
        or lower.endswith(GENERATED_SUFFIXES)
    )


def is_code_indexable(path: str, size: int) -> bool:
    if size > MAX_FILE_BYTES:
        return False
    for prefix in SKIP_DIR_PREFIXES:
        if path.startswith(prefix) or f"/{prefix}" in path:
            return False
    if _base(path).startswith(".") or is_boilerplate(path):
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
        if i % WINDOW_LINES == 0:
            points.append(i)
    points.append(len(lines))
    return points


def _code_header(f: RawFile) -> str:
    # No line numbers: the URL anchor carries them, and keeping them out of the
    # text means code that only moved keeps its text, its id and its vector.
    return f"// File: {f.path} ({f.language})\n"


def _fit(lines: List[str], start: int, budget: int) -> List[Tuple[int, int, str]]:
    """``lines`` (the first is line ``start``) as (first, last, text) pieces of at
    most ``budget`` characters, cut between lines; a single longer line (a
    minified one) is cut inside it. Nothing is dropped."""
    pieces: List[Tuple[int, int, str]] = []
    buf: List[str] = []
    first = start
    size = 0
    for offset, line in enumerate(lines):
        number = start + offset
        while len(line) > budget:
            if buf:
                pieces.append((first, number - 1, "\n".join(buf)))
                buf, size = [], 0
            pieces.append((number, number, line[:budget]))
            line = line[budget:]
        if buf and size + 1 + len(line) > budget:
            pieces.append((first, number - 1, "\n".join(buf)))
            buf, size = [], 0
        if not buf:
            first = number
            size = len(line)
        else:
            size += 1 + len(line)
        buf.append(line)
    if buf:
        pieces.append((first, start + len(lines) - 1, "\n".join(buf)))
    return pieces


def _segments(lines: List[str], language: str) -> List[Tuple[int, List[str]]]:
    """Whole file up to SPLIT_LINES, else split on function/class boundaries
    (falling back to every WINDOW_LINES lines): (first line, lines) pairs."""
    if len(lines) <= SPLIT_LINES:
        return [(1, lines)]
    out: List[Tuple[int, List[str]]] = []
    start = 0
    for end in _split_points(lines, language):
        if end > start:
            out.append((start + 1, lines[start:end]))
            start = end
    return out


def chunk_file(f: RawFile, owner: str) -> List[Chunk]:
    """The file's segments, each cut to MAX_CODE_CHUNK_CHARS without losing any
    of it. A chunk's id is keyed on its text, so a chunk only gets a new id when
    its own code changes."""
    if len(f.content.strip()) < MIN_CODE_CHARS:
        return []
    header = _code_header(f)
    budget = MAX_CODE_CHUNK_CHARS - len(header)
    pieces = [
        piece
        for first, seg in _segments(f.content.split("\n"), f.language)
        for piece in _fit(seg, first, budget)
        if piece[2].strip()
    ]
    keys = _occurrence_keys(
        [
            f"github_code:{owner}/{f.repo}:{f.path}:{content_hash(text)[:16]}"
            for _, _, text in pieces
        ]
    )
    return [
        Chunk(
            id=deterministic_id(key),
            content=header + text,
            source="github_code",
            type="code",
            repo=f.repo,
            url=f"{f.url}#L{first}-L{last}",
            path=f.path,
            language=f.language,
        )
        for key, (first, last, text) in zip(keys, pieces, strict=True)
    ]


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
        except (GitHubAPIError, httpx2.HTTPError):
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
        except (GitHubAPIError, httpx2.HTTPError) as exc:
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
    owner: str, repo: str, branch: str, doc: RepoDoc, section: Section, key: str
) -> Chunk:
    title = f"{doc.path} — {section.heading}" if section.heading else doc.path
    return Chunk(
        id=deterministic_id(key),
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
                sections = doc_sections(doc)
                # Keyed on the heading trail, not the position: adding a
                # section no longer renumbers every section after it.
                keys = _occurrence_keys(
                    [
                        f"github_docs:{repo_owner}/{repo_name}:{doc.path}:{s.heading}"
                        for s in sections
                    ]
                )
                for key, section in zip(keys, sections, strict=True):
                    chunks.append(
                        _doc_chunk(repo_owner, repo_name, branch, doc, section, key)
                    )
        except (GitHubAPIError, httpx2.HTTPError) as exc:
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
            ["git", "rev-parse", "HEAD"],  # noqa: S607 — the host's git, from PATH
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def chunker_settings() -> dict:
    """The parameters the chunks were cut with, recorded in the manifest: two
    builds with different settings are different corpora even from one input."""
    return {
        "code": {
            "max_chunk_chars": MAX_CODE_CHUNK_CHARS,
            "split_lines": SPLIT_LINES,
            "window_lines": WINDOW_LINES,
            "min_code_chars": MIN_CODE_CHARS,
            "max_file_bytes": MAX_FILE_BYTES,
        },
        "docs": {
            "max_chunk_chars": MAX_DOC_CHUNK_CHARS,
            "min_section_chars": MIN_SECTION_CHARS,
            "max_docs_per_repo": MAX_INDEXED_DOCS_PER_REPO,
        },
        "readme": {"max_chunk_chars": MAX_DOC_CHUNK_CHARS},
    }


# Every record's columns, for the Hub's viewer and ``datasets.load_dataset``.
# An optional field absent from a record reads as null.
FEATURES = (
    "id",
    "content",
    "source",
    "type",
    "repo",
    "url",
    "path",
    "language",
    "content_hash",
)


def _size_category(total: int) -> str:
    if total < 1_000:
        return "n<1K"
    if total < 10_000:
        return "1K<n<10K"
    if total < 100_000:
        return "10K<n<100K"
    return "100K<n<1M"


def dataset_card(manifest: dict, repo: str, username: str) -> str:
    total = sum(f.get("records", 0) for f in manifest["files"])
    lines = [
        "---",
        "pretty_name: Portfolio knowledge base",
        "license: other",
        "language:",
        "  - en",
        "  - fr",
        "size_categories:",
        f"  - {_size_category(total)}",
        "task_categories:",
        "  - text-retrieval",
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
    lines.append("dataset_info:")
    for f in manifest["files"]:
        lines.append(f"  - config_name: {f['source']}")
        lines.append("    features:")
        for name in FEATURES:
            lines.append(f"      - name: {name}\n        dtype: string")
        lines.append("    splits:")
        lines.append(f"      - name: train\n        num_examples: {f['records']}")
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
        "| `type` | `bio`, `skills`, `project` (`profile`); `bio`, `contact`, "
        "`readme` (`github`); `code`; `docs` |",
        "| `repo` | Repository name, when applicable |",
        "| `url` | Source URL; for code, a permalink with a line anchor |",
        "| `path` | File path within the repository (`github_code`, `github_docs`) |",
        "| `language` | Programming language (`github_code`); `Markdown` for "
        "`github_docs` |",
        "| `content_hash` | SHA-256 of `content`: an indexer that already holds "
        "this hash can keep its vector |",
        "",
        "Records are sorted by `id`, so a week-to-week diff shows only what "
        "actually changed.",
        "No embedding vectors are stored: the corpus stays independent of "
        "whichever embedding model indexes it.",
        "",
        "## Provenance",
        "",
        f"- Schema version: `{manifest.get('schema_version', 1)}`",
        f"- Generated at: `{manifest.get('generated_at', '')}`",
        f"- Generator: `{manifest.get('generator', GENERATOR_NAME)}`",
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
        "schema_version": SCHEMA_VERSION,
        # Whose corpus this is: the card names them, also when a push rewrites it.
        "owner": username,
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

    manifest["chunker"] = chunker_settings()
    # What the build read: each repo's branch and tree sha, so two manifests
    # tell whether a difference comes from the inputs or from the generator.
    manifest["inputs"] = {
        slug: {"branch": branch, "tree": tree}
        for slug, (branch, tree) in sorted(client.trees_read.items())
    }
    manifest["files"] = sorted(files, key=lambda f: f["path"])
    write_manifest(out, manifest, hf_repo, username)
    return manifest


def write_manifest(out: Path, manifest: dict, hf_repo: str, username: str) -> None:
    """``manifest.json`` and the card that describes it."""
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(
        dataset_card(manifest, hf_repo, username), encoding="utf-8"
    )


# --- push --------------------------------------------------------------------


class CorpusMoved(JobError):
    """The corpus repo got a commit between this push's read and its commit."""


def _remote_manifest(api, repo_id: str, revision: str) -> Optional[dict]:
    """The manifest at ``revision``, or None when that commit has none."""
    from huggingface_hub.errors import EntryNotFoundError

    try:
        local = api.hf_hub_download(
            repo_id, "manifest.json", repo_type="dataset", revision=revision
        )
    except EntryNotFoundError:
        return None
    try:
        manifest = json.loads(Path(local).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise JobError(f"manifest.json in {repo_id} is not valid JSON: {exc}") from exc
    return manifest if isinstance(manifest, dict) else None


def _carry_forward(
    api, repo_id: str, parent: str, directory: Path, manifest: dict
) -> List[dict]:
    """Copy into ``directory`` the splits of the published corpus this export did
    not rebuild, so the commit stays a complete snapshot; their manifest entries.

    A split is only carried from a corpus of the same schema version: mixing
    two chunk layouts in one snapshot would make the manifest lie about half of
    it. Each carried file is checked against the hash its manifest gives.
    """
    remote = _remote_manifest(api, repo_id, parent)
    if not remote:
        return []
    built = {f["source"] for f in manifest.get("files") or []}
    missing = [
        f
        for f in remote.get("files") or []
        if isinstance(f, dict)
        and f.get("source") in KNOWN_SOURCES
        and f["source"] not in built
    ]
    if not missing:
        return []
    remote_version = remote.get("schema_version", 1)
    if remote_version != manifest.get("schema_version"):
        names = ", ".join(sorted(f["source"] for f in missing))
        raise JobError(
            f"the published corpus is schema version {remote_version} and this "
            f"build is {manifest.get('schema_version')}: rebuild every source "
            f"once (missing here: {names})"
        )
    carried = []
    for entry in missing:
        # The path is the Hub's, not ours: only the split's own file is read.
        path = SPLIT_FILES[entry["source"]]
        local = Path(
            api.hf_hub_download(repo_id, path, repo_type="dataset", revision=parent)
        )
        data = local.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            raise JobError(
                f"{path} in {repo_id} does not match its manifest hash; "
                "rebuild that source"
            )
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_bytes(data)
        carried.append({**entry, "path": path})
        logger.info("push: carried %s forward from %s", path, parent[:7])
    return carried


def push_corpus(creds: Credentials, directory: Path, repo_id: str) -> str:
    """Commit the exported directory to a private HF dataset in one commit.

    The commit is a complete snapshot: the splits this export did not build are
    carried over from the published corpus, any other ``data/`` file is
    deleted, and the commit only lands on the version that was read — a push
    racing another one fails with :class:`CorpusMoved` instead of mixing them.
    """
    from huggingface_hub.errors import HfHubHTTPError

    from server.services.hub_repo import HubRepoError, open_repo
    from server.services.huggingface import _api, ensure_private_dataset_repo

    if not directory.is_dir():
        raise JobError(f"{directory} does not exist — run the export first")
    manifest_path = directory / "manifest.json"
    # The manifest is what the ingest side reads to discover the splits.
    if not manifest_path.is_file():
        raise JobError(f"no manifest.json in {directory} — the export did not complete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Opened like every dataset repo (services/hub_repo.py): a bad token fails
    # here, before megabytes are uploaded — a fine-grained token missing write
    # access otherwise only surfaces at the final commit — and a bare name,
    # which would 404 on commit, is completed with the namespace.
    try:
        repo_id = open_repo(creds, repo_id).repo_id
    except HubRepoError as exc:
        raise JobError(str(exc)) from exc
    api = _api(creds)
    ensure_private_dataset_repo(api, repo_id)
    parent = getattr(api.repo_info(repo_id, repo_type="dataset"), "sha", None)
    parent = parent if isinstance(parent, str) and parent else None

    if parent:
        carried = _carry_forward(api, repo_id, parent, directory, manifest)
        if carried:
            manifest["files"] = sorted(
                [*(manifest.get("files") or []), *carried], key=lambda f: f["path"]
            )
            write_manifest(
                directory, manifest, repo_id, str(manifest.get("owner") or "")
            )

    files = manifest.get("files") or []
    total = sum(f.get("records", 0) for f in files)
    sha = manifest.get("source_commit") or ""
    title = "Corpus refresh" + (f" ({sha[:7]})" if sha else "")
    description = "\n".join(
        [
            f"{total} records across {len(files)} splits.",
            *(f"- {f['source']}: {f['records']} records ({f['path']})" for f in files),
            f"\nGenerated from {GENERATOR_NAME}@{sha}" if sha else "",
        ]
    )

    logger.info("uploading %s to %s", directory, repo_id)
    try:
        api.upload_folder(
            folder_path=str(directory),
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=title,
            commit_description=description,
            # Every data file the manifest no longer lists goes: the uploaded
            # files themselves are never deleted by these patterns.
            delete_patterns=["data/*"],
            **({"parent_commit": parent} if parent else {}),
        )
    except HfHubHTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (409, 412):
            raise CorpusMoved(
                f"{repo_id} changed while the corpus was being pushed; run it again"
            ) from exc
        raise
    return f"https://huggingface.co/datasets/{repo_id}"


# --- after the push ----------------------------------------------------------

REINDEX_TIMEOUT_SECONDS = 30.0


async def notify_reindex(
    transport: Optional[httpx2.AsyncBaseTransport] = None,
) -> Optional[str]:
    """Tell the site that indexes the corpus to read it again: one POST to
    ``CORPUS_REINDEX_URL`` with ``CORPUS_REINDEX_SECRET`` as a bearer token.

    None when it answered 2xx; otherwise what went wrong, for the run's
    report — the corpus is published either way, so a site that is down
    never fails the run. The URL is the operator's: it is called as it is, and
    a redirect is not followed (the secret would follow it).
    """
    url, secret = config.corpus_reindex_url, config.corpus_reindex_secret
    try:
        async with httpx2.AsyncClient(
            timeout=REINDEX_TIMEOUT_SECONDS, transport=transport
        ) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {secret}"}
            )
    except httpx2.HTTPError as exc:
        return f"The reindex call failed: {type(exc).__name__}: {exc}"
    if response.is_success:
        return None
    return f"The reindex call answered {response.status_code}"


def reindex_configured() -> bool:
    return bool(config.corpus_reindex_url and config.corpus_reindex_secret)
