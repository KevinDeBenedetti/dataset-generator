"""GitHub reads shared by the corpus and Q&A dataset jobs.

Ported from portfolio-next (``src/lib/rag/github*.ts``). Only public data is
read; the token only raises the rate limit from 60 to 5000 requests/hour.
"""

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from server.services.github import GitHubService

logger = logging.getLogger(__name__)

MAX_README_CHARS = 3000
MAX_REPOS = 500

DOC_EXTENSIONS = (".md", ".mdx", ".markdown", ".txt", ".rst")
MAX_DOC_BYTES = 50 * 1024


def deterministic_id(key: str) -> str:
    """UUIDv5 (URL namespace) over an identity key.

    Must stay byte-identical to the Go/TS implementations: the consumer upserts
    by id, so a divergence silently duplicates the whole corpus on next ingest.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class GitHubAPIError(RuntimeError):
    pass


@dataclass
class RepoData:
    name: str
    description: str = ""
    stars: int = 0
    topics: List[str] = field(default_factory=list)
    language: str = ""
    homepage: str = ""
    url: str = ""
    readme: str = ""


@dataclass
class GitHubProfile:
    login: str
    name: str = ""
    bio: str = ""
    company: str = ""
    location: str = ""
    email: str = ""
    blog: str = ""
    twitter: str = ""
    public_repos: int = 0
    followers: int = 0
    following: int = 0
    html_url: str = ""


@dataclass
class GitHubSnapshot:
    username: str
    profile: Optional[GitHubProfile]
    repos: List[RepoData]
    fetched_at: str


@dataclass
class RepoDoc:
    path: str
    content: str


def split_slug(slug: str, default_owner: str) -> Tuple[str, str]:
    slug = slug.removeprefix("https://github.com/").removeprefix("github.com/")
    parts = slug.split("/")
    if len(parts) == 2:
        return parts[0], parts[1]
    return default_owner, slug


def _str(data: dict, key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _int(data: dict, key: str) -> int:
    value = data.get(key)
    return value if isinstance(value, int) else 0


class CorpusGitHubClient(GitHubService):
    """GitHubService plus the tree/content/profile reads the corpus needs."""

    def __init__(self, token: Optional[str] = None, timeout: float = 30.0):
        super().__init__(token, timeout)
        # Set once a response shows the quota is gone, so every later call fails
        # fast with the reset time instead of a cascade of vague 403s.
        self.rate_limited_until: Optional[str] = None
        self._branches: Dict[str, str] = {}

    def _raise_for(self, resp: httpx.Response, what: str) -> None:
        if resp.status_code == 404:
            raise GitHubAPIError(f"{what}: not found")
        if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
            reset = int(resp.headers.get("x-ratelimit-reset") or 0)
            when = (
                datetime.fromtimestamp(reset, timezone.utc).isoformat()
                if reset
                else "unknown"
            )
            self.rate_limited_until = when
            raise GitHubAPIError(
                f"{what}: GitHub rate limit exhausted (resets at {when}). "
                "Set GITHUB_TOKEN to raise it from 60 to 5000 req/h."
            )
        raise GitHubAPIError(f"{what}: HTTP {resp.status_code}")

    def _guard(self) -> None:
        if self.rate_limited_until:
            raise GitHubAPIError(
                f"GitHub rate limit exhausted (resets at {self.rate_limited_until})"
            )

    async def list_user_repos(self, username: str) -> List[str]:
        """Public, non-fork, non-archived repos as ``owner/name`` slugs."""
        repos = await self.list_public_repos(username, max_repos=MAX_REPOS)
        return [
            r["full_name"]
            for r in repos
            if r.get("full_name")
            and not r.get("fork")
            and not r.get("archived")
            and not r.get("private")
        ]

    async def fetch_profile(self, username: str) -> GitHubProfile:
        resp = await self.client.get(f"/users/{quote(username)}")
        if resp.status_code != 200:
            self._raise_for(resp, f"github profile {username}")
        d = resp.json()
        return GitHubProfile(
            login=_str(d, "login"),
            name=_str(d, "name"),
            bio=_str(d, "bio"),
            company=_str(d, "company"),
            location=_str(d, "location"),
            email=_str(d, "email"),
            blog=_str(d, "blog"),
            twitter=_str(d, "twitter_username"),
            public_repos=_int(d, "public_repos"),
            followers=_int(d, "followers"),
            following=_int(d, "following"),
            html_url=_str(d, "html_url"),
        )

    async def fetch_readme(self, owner: str, repo: str) -> str:
        """Best effort: a repo without a README is normal, so failures give ''."""
        try:
            text = await self.get_readme(owner, repo) or ""
        except httpx.HTTPError:
            return ""
        if len(text) > MAX_README_CHARS:
            return f"{text[:MAX_README_CHARS]}\n\n[README truncated]"
        return text

    async def fetch_repo(self, owner: str, repo: str) -> RepoData:
        self._guard()
        resp = await self.client.get(f"/repos/{owner}/{repo}")
        if resp.status_code != 200:
            self._raise_for(resp, f"github repo {owner}/{repo}")
        d = resp.json()
        self._branches[f"{owner}/{repo}"] = d.get("default_branch") or "main"
        return RepoData(
            name=d.get("name") or repo,
            description=d.get("description") or "",
            stars=d.get("stargazers_count") or 0,
            topics=d.get("topics") or [],
            language=d.get("language") or "",
            homepage=d.get("homepage") or "",
            url=d.get("html_url") or "",
            readme=await self.fetch_readme(owner, repo),
        )

    async def default_branch(self, owner: str, repo: str) -> str:
        key = f"{owner}/{repo}"
        if key not in self._branches:
            try:
                resp = await self.client.get(f"/repos/{owner}/{repo}")
                branch = (
                    resp.json().get("default_branch")
                    if resp.status_code == 200
                    else None
                )
            except httpx.HTTPError:
                branch = None
            self._branches[key] = branch or "main"
        return self._branches[key]

    async def repo_tree(self, owner: str, repo: str, branch: str) -> List[dict]:
        """The full recursive file tree of a branch."""
        self._guard()
        resp = await self.client.get(
            f"/repos/{owner}/{repo}/git/trees/{quote(branch, safe='')}",
            params={"recursive": "1"},
        )
        if resp.status_code != 200:
            self._raise_for(resp, f"github tree for {owner}/{repo}")
        return resp.json().get("tree") or []

    async def file_content(self, owner: str, repo: str, path: str) -> str:
        self._guard()
        resp = await self.client.get(f"/repos/{owner}/{repo}/contents/{quote(path)}")
        if resp.status_code != 200:
            self._raise_for(resp, f"github content {owner}/{repo}/{path}")
        data = resp.json()
        content = data.get("content") or ""
        if data.get("encoding") != "base64":
            return content
        return base64.b64decode(content.replace("\n", "")).decode(
            "utf-8", errors="replace"
        )


async def fetch_snapshot(
    client: CorpusGitHubClient, username: str
) -> Tuple[GitHubSnapshot, List[str]]:
    """Profile + every public repo. Per-repo failures are collected, not raised."""
    profile = await client.fetch_profile(username)
    slugs = await client.list_user_repos(username)

    repos: List[RepoData] = []
    errors: List[str] = []
    for slug in slugs:
        owner, name = split_slug(slug, username)
        try:
            repos.append(await client.fetch_repo(owner, name))
        except (GitHubAPIError, httpx.HTTPError) as exc:
            errors.append(f"{slug}: {exc}")

    snapshot = GitHubSnapshot(
        username=username,
        profile=profile,
        repos=repos,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    return snapshot, errors


async def fetch_repo_docs(
    client: CorpusGitHubClient,
    owner: str,
    repo: str,
    limit: int,
    max_chars: int = 0,
) -> List[RepoDoc]:
    """A repo's ``docs/`` markdown files. Best effort: failures yield []."""
    try:
        branch = await client.default_branch(owner, repo)
        tree = await client.repo_tree(owner, repo, branch)
    except (GitHubAPIError, httpx.HTTPError) as exc:
        logger.warning("docs/ tree for %s/%s unavailable: %s", owner, repo, exc)
        return []

    candidates = [
        e
        for e in tree
        if e.get("type") == "blob"
        and e.get("path", "").lower().startswith("docs/")
        and e.get("path", "").lower().endswith(DOC_EXTENSIONS)
        and (e.get("size") or 0) <= MAX_DOC_BYTES
    ][:limit]

    docs: List[RepoDoc] = []
    for entry in candidates:
        try:
            content = await client.file_content(owner, repo, entry["path"])
        except (GitHubAPIError, httpx.HTTPError) as exc:
            logger.warning("skipping %s/%s/%s: %s", owner, repo, entry["path"], exc)
            continue
        if not content.strip():
            continue
        if max_chars > 0 and len(content) > max_chars:
            content = f"{content[:max_chars]}\n[...truncated]"
        docs.append(RepoDoc(path=entry["path"], content=content))
    return docs


async def gather_limited(limit: int, coros) -> list:
    """``asyncio.gather`` with at most ``limit`` coroutines in flight, in order."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))
