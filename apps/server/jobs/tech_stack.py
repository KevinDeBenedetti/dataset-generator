"""What a repo is built with, read from its dependency manifests.

GitHub's primary language and hand-set topics alone made a poor stack: most
repos carry few topics, so nearly every tool showed up in one project only,
and "what is the main stack?" had no real answer. Manifests (package.json,
pyproject.toml, go.mod, …) and a few telltale files (Dockerfile, Chart.yaml,
workflows) say what is actually used, and stay right without upkeep.

Only dependencies listed in :data:`DEPENDENCY_TECH` count: a raw dependency
list is mostly plumbing (``@types/node``, ``httpx``, eslint plugins) that says
nothing about someone's stack. Extending the catalog is the way to recognise
more technologies.
"""

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Dict, Iterable, List, Set

if TYPE_CHECKING:
    from server.jobs.github_snapshot import RepoData

logger = logging.getLogger(__name__)

# Bounds the reads per repo: a monorepo can hold dozens of package.json files,
# and past a handful they only repeat the same dependencies.
MAX_MANIFESTS_PER_REPO = 15
MAX_MANIFEST_BYTES = 200 * 1024

# Anything under these is vendored, generated, or sample code — not the stack.
_SKIP_DIRS = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|\.venv|venv|site-packages|\.next|"
    r"\.nuxt|coverage|fixtures|testdata|examples?)/"
)

# --- catalog -----------------------------------------------------------------

# Exact dependency name (lowercased; Python names with ``_`` → ``-``) → label.
DEPENDENCY_TECH: Dict[str, str] = {
    # JavaScript / TypeScript
    "next": "Next.js",
    "nuxt": "Nuxt",
    "@nuxt/content": "Nuxt Content",
    "vue": "Vue",
    "react": "React",
    "svelte": "Svelte",
    "@sveltejs/kit": "SvelteKit",
    "astro": "Astro",
    "vitepress": "VitePress",
    "vite": "Vite",
    "tailwindcss": "Tailwind CSS",
    "typescript": "TypeScript",
    "express": "Express",
    "fastify": "Fastify",
    "hono": "Hono",
    "@nestjs/core": "NestJS",
    "drizzle-orm": "Drizzle ORM",
    "prisma": "Prisma",
    "@prisma/client": "Prisma",
    "next-auth": "Auth.js",
    "@auth/core": "Auth.js",
    "zod": "Zod",
    "pinia": "Pinia",
    "zustand": "Zustand",
    "@tanstack/react-query": "TanStack Query",
    "vitest": "Vitest",
    "jest": "Jest",
    "@playwright/test": "Playwright",
    "cypress": "Cypress",
    "storybook": "Storybook",
    "langchain": "LangChain",
    "@langchain/core": "LangChain",
    "@langchain/langgraph": "LangGraph",
    "openai": "OpenAI API",
    "@anthropic-ai/sdk": "Anthropic API",
    "@anthropic-ai/claude-agent-sdk": "Claude Agent SDK",
    "@qdrant/js-client-rest": "Qdrant",
    "ioredis": "Redis",
    "redis": "Redis",
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mongodb": "MongoDB",
    "mongoose": "MongoDB",
    "@supabase/supabase-js": "Supabase",
    "@directus/sdk": "Directus",
    "three": "Three.js",
    "d3": "D3.js",
    "electron": "Electron",
    "socket.io": "Socket.IO",
    "oxlint": "Oxlint",
    "@biomejs/biome": "Biome",
    # Python
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "sqlalchemy": "SQLAlchemy",
    "alembic": "Alembic",
    "pydantic": "Pydantic",
    "celery": "Celery",
    "langgraph": "LangGraph",
    "anthropic": "Anthropic API",
    "claude-agent-sdk": "Claude Agent SDK",
    "huggingface-hub": "Hugging Face Hub",
    "transformers": "Hugging Face Transformers",
    "sentence-transformers": "Sentence Transformers",
    "torch": "PyTorch",
    "pandas": "pandas",
    "scikit-learn": "scikit-learn",
    "qdrant-client": "Qdrant",
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "pytest": "pytest",
    "beautifulsoup4": "Beautiful Soup",
    "scrapy": "Scrapy",
    "playwright": "Playwright",
    "langfuse": "Langfuse",
    "streamlit": "Streamlit",
    "typer": "Typer",
    "ruff": "Ruff",
    # Go
    "github.com/gin-gonic/gin": "Gin",
    "github.com/labstack/echo/v4": "Echo",
    "github.com/gofiber/fiber/v2": "Fiber",
    "gorm.io/gorm": "GORM",
    "github.com/jackc/pgx/v5": "PostgreSQL",
    "github.com/redis/go-redis/v9": "Redis",
    "github.com/spf13/cobra": "Cobra",
    "k8s.io/client-go": "Kubernetes",
    # Rust
    "tokio": "Tokio",
    "axum": "Axum",
    "actix-web": "Actix Web",
    "clap": "clap",
}

# Dependency-name prefixes for families published as many packages.
DEPENDENCY_PREFIXES = (
    ("langchain-", "LangChain"),
    ("@langchain/", "LangChain"),
)

# Topic or language spellings folded onto the catalog's labels, so a repo
# tagged ``fastapi`` and one depending on ``fastapi`` count as the same thing.
ALIASES: Dict[str, str] = {
    "nextjs": "Next.js",
    "next": "Next.js",
    "nuxt": "Nuxt",
    "nuxtjs": "Nuxt",
    "nuxt-content": "Nuxt Content",
    "vue": "Vue",
    "vuejs": "Vue",
    "react": "React",
    "reactjs": "React",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "docker": "Docker",
    "docker-compose": "Docker Compose",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "helm": "Helm",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "argocd": "Argo CD",
    "github-actions": "GitHub Actions",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "openai": "OpenAI API",
    "tailwindcss": "Tailwind CSS",
    "tailwind": "Tailwind CSS",
    "vitepress": "VitePress",
    "supabase": "Supabase",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "redis": "Redis",
    "qdrant": "Qdrant",
    "grafana": "Grafana",
    "prometheus": "Prometheus",
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "go": "Go",
    "golang": "Go",
    "rust": "Rust",
    "shell": "Shell",
    "bash": "Shell",
}

# Labels counted as programming languages rather than tools.
LANGUAGES = frozenset(
    {
        "Python",
        "TypeScript",
        "JavaScript",
        "Go",
        "Rust",
        "Shell",
        "Java",
        "Kotlin",
        "Swift",
        "C",
        "C++",
        "C#",
        "Ruby",
        "PHP",
        "Vue",
        "HCL",
        "Dart",
    }
)

# Linters, test runners, migration tools: real, but they say how a project is
# maintained rather than what it is built with — ranked on their own so they
# don't crowd frameworks out of "the main stack".
TOOLING = frozenset(
    {
        "Alembic",
        "Biome",
        "Cypress",
        "Jest",
        "Oxlint",
        "Playwright",
        "Ruff",
        "Storybook",
        "Vitest",
        "pytest",
    }
)

# Repo topics that say what a repo is, not a technology it uses.
NON_TECH_TOPICS = frozenset(
    {
        "awesome",
        "docs",
        "documentation",
        "dotfiles",
        "hacktoberfest",
        "issue-templates",
        "markdown",
        "notes",
        "portfolio",
        "pull-request-template",
        "pull-request-templates",
        "template",
        "templates",
    }
)


def canonical(name: str) -> str:
    """The catalog label for a topic/language spelling, else the name as is."""
    return ALIASES.get(name.strip().lower(), name.strip())


def tech_for_dependency(name: str) -> str:
    """Catalog label for a dependency name, or '' when it isn't a known one."""
    exact = name.strip().lower()
    # PyPI treats ``_`` and ``-`` alike; npm/Go/Cargo names never contain ``_``
    # where it would matter, so trying both is safe.
    key = exact.replace("_", "-")
    for candidate in (exact, key):
        if candidate in DEPENDENCY_TECH:
            return DEPENDENCY_TECH[candidate]
    for prefix, label in DEPENDENCY_PREFIXES:
        if key.startswith(prefix):
            return label
    return ""


# --- manifest parsing --------------------------------------------------------

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _pep508_names(specs: Iterable) -> List[str]:
    names = []
    for spec in specs:
        if isinstance(spec, str):
            match = _PEP508_NAME.match(spec)
            if match:
                names.append(match.group(1))
    return names


def package_json_deps(text: str) -> List[str]:
    data = json.loads(text)
    if not isinstance(data, dict):
        return []
    names: List[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names += list(section)
    return names


def pyproject_deps(text: str) -> List[str]:
    data = tomllib.loads(text)
    project = data.get("project") or {}
    names = _pep508_names(project.get("dependencies") or [])
    for group in (project.get("optional-dependencies") or {}).values():
        names += _pep508_names(group or [])
    for group in (data.get("dependency-groups") or {}).values():
        names += _pep508_names(group or [])
    poetry = (data.get("tool") or {}).get("poetry") or {}
    names += [n for n in (poetry.get("dependencies") or {}) if n != "python"]
    for group in (poetry.get("group") or {}).values():
        names += list((group or {}).get("dependencies") or {})
    return names


def requirements_deps(text: str) -> List[str]:
    lines = (line.split("#", 1)[0] for line in text.splitlines())
    return _pep508_names(line for line in lines if not line.strip().startswith("-"))


def go_mod_deps(text: str) -> List[str]:
    names = []
    in_block = False
    for line in text.splitlines():
        line = line.split("//", 1)[0].strip()
        if line.startswith("require ("):
            in_block = True
        elif in_block and line == ")":
            in_block = False
        elif in_block and line:
            names.append(line.split()[0])
        elif line.startswith("require "):
            names.append(line.split()[1])
    return names


def cargo_deps(text: str) -> List[str]:
    data = tomllib.loads(text)
    names: List[str] = []
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        names += list(data.get(key) or {})
    return names


def _parser_for(path: str) -> Callable[[str], List[str]] | None:
    base = path.rsplit("/", 1)[-1].lower()
    if base == "package.json":
        return package_json_deps
    if base == "pyproject.toml":
        return pyproject_deps
    if base.startswith("requirements") and base.endswith(".txt"):
        return requirements_deps
    if base == "go.mod":
        return go_mod_deps
    if base == "cargo.toml":
        return cargo_deps
    return None


def file_signals(paths: Iterable[str]) -> Set[str]:
    """Technologies a file's mere presence gives away."""
    found: Set[str] = set()
    for path in paths:
        if _SKIP_DIRS.search(path):
            continue
        lower = path.lower()
        base = lower.rsplit("/", 1)[-1]
        if (
            base == "dockerfile"
            or base.startswith("dockerfile.")
            or base.endswith(".dockerfile")
        ):
            found.add("Docker")
        elif re.fullmatch(r"(docker-)?compose(\.[\w-]+)?\.ya?ml", base):
            found.add("Docker Compose")
        elif base == "chart.yaml":
            found.add("Helm")
        elif base in ("kustomization.yaml", "kustomization.yml"):
            found.add("Kubernetes")
        elif base.endswith(".tf"):
            found.add("Terraform")
        elif base == "ansible.cfg" or re.search(r"(^|/)roles/[^/]+/tasks/", lower):
            found.add("Ansible")
        elif lower.startswith(".github/workflows/") and base.endswith(
            (".yml", ".yaml")
        ):
            found.add("GitHub Actions")
    return found


def manifest_paths(paths: Iterable[str]) -> List[str]:
    """Dependency manifests worth reading, shallowest first, capped."""
    candidates = [p for p in paths if _parser_for(p) and not _SKIP_DIRS.search(p)]
    candidates.sort(key=lambda p: (p.count("/"), p))
    return candidates[:MAX_MANIFESTS_PER_REPO]


async def detect_technologies(
    tree: List[dict], read: Callable[[str], Awaitable[str]]
) -> List[str]:
    """Technologies used by a repo, from its file tree and manifests.

    Best effort per file: an unreadable or malformed manifest is skipped, the
    rest still count. The result is sorted, so it is stable across runs.
    """
    blobs = [
        e
        for e in tree
        if e.get("type") == "blob" and (e.get("size") or 0) <= MAX_MANIFEST_BYTES
    ]
    paths = [e.get("path", "") for e in blobs]
    found = file_signals(paths)
    for path in manifest_paths(paths):
        parse = _parser_for(path)
        try:
            names = parse(await read(path)) if parse else []
        except Exception as exc:  # malformed manifest or failed read
            logger.debug("skipping manifest %s: %s", path, exc)
            continue
        found.update(t for t in map(tech_for_dependency, names) if t)
    return sorted(found)


# --- ranking -----------------------------------------------------------------


@dataclass
class StackEntry:
    name: str
    projects: int


@dataclass
class RankedStack:
    languages: List[StackEntry]
    # Frameworks, libraries, platforms — what "the stack" means to a visitor.
    tools: List[StackEntry]
    # See TOOLING.
    tooling: List[StackEntry]
    total_projects: int


def repo_technologies(repo: "RepoData") -> List[str]:
    """A repo's language, topics and detected technologies, deduplicated
    case-insensitively on their canonical label (first spelling wins)."""
    names = ([repo.language] if repo.language else []) + list(repo.topics)
    names += list(repo.technologies)
    seen: Set[str] = set()
    out: List[str] = []
    for name in names:
        if not name.strip() or name.strip().lower() in NON_TECH_TOPICS:
            continue
        label = canonical(name)
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out


def rank_stack(repos: List["RepoData"]) -> RankedStack:
    """Languages and tools ranked by how many repos use them. Ties sort
    alphabetically, so the ranking is stable from one run to the next."""
    counts: Dict[str, int] = {}
    labels: Dict[str, str] = {}
    languages = {canonical(r.language).lower() for r in repos if r.language}
    languages |= {lang.lower() for lang in LANGUAGES}
    for repo in repos:
        for label in repo_technologies(repo):
            key = label.lower()
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, label)

    ranked = sorted(counts, key=lambda k: (-counts[k], labels[k].lower()))
    entries = [StackEntry(labels[k], counts[k]) for k in ranked]
    tooling = {t.lower() for t in TOOLING}
    return RankedStack(
        languages=[e for e in entries if e.name.lower() in languages],
        tools=[
            e
            for e in entries
            if e.name.lower() not in languages and e.name.lower() not in tooling
        ],
        tooling=[e for e in entries if e.name.lower() in tooling],
        total_projects=len(repos),
    )


def main_entries(entries: List[StackEntry], limit: int) -> List[StackEntry]:
    """The entries shared by several projects — what "main" means — or, when
    too few are, the top of the ranking anyway."""
    shared = [e for e in entries if e.projects >= 2]
    return (shared if len(shared) >= 3 else entries)[:limit]


def format_stack_entries(entries: List[StackEntry]) -> str:
    """``TypeScript (4 projects), Go (1 project)``."""
    return ", ".join(
        f"{e.name} ({e.projects} project{'s' if e.projects > 1 else ''})"
        for e in entries
    )
