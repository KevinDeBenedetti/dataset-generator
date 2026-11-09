"""Browse your public GitHub data: what a GitHub-fed dataset is made of.

Read-only, public data only (a token only raises the rate limit), scoped to
the GitHub username saved in Settings. It reuses the client and the readers
of the Q&A job (jobs/github_snapshot.py, jobs/qa_dataset.py), so what the
page shows — a README cleaned and cut as the model sees it, the ``docs/``
files, the detected stack, the overview text — is exactly what a generation
would use.

Every answer is cached a few minutes per username: a repo's detail costs up
to a few dozen GitHub requests (README, tree, dependency manifests), and the
quota is 60 requests an hour without a token. Per username, not per caller —
so a private repo is refused before anything of it is read, even when the
caller's token could read it: cached, it would reach anyone who saves the
same username.
"""

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Hashable, List, Optional, TypeVar

import httpx

from server.jobs.github_snapshot import (
    DOC_EXTENSIONS,
    MAX_DOC_BYTES,
    MAX_README_CHARS,
    CorpusGitHubClient,
    GitHubAPIError,
    RepoData,
)
from server.jobs.qa_dataset import MAX_DOC_CHARS, MAX_DOCS_PER_REPO, overview_context
from server.services.credentials import GITHUB_TOKEN, Credentials

logger = logging.getLogger(__name__)

T = TypeVar("T")

CACHE_TTL_SECONDS = 300.0
CACHE_MAX_ENTRIES = 512
MAX_DOC_PATH_CHARS = 512


class GitHubNotConfiguredError(ValueError):
    """No GitHub username in Settings."""


class GitHubNotFoundError(LookupError):
    """Unknown user, repo or file — or one outside the configured account."""


class GitHubRateLimitError(RuntimeError):
    """The GitHub API quota is exhausted."""


class GitHubUnavailableError(RuntimeError):
    """GitHub failed to answer."""


# --- cache --------------------------------------------------------------------

_cache: "OrderedDict[Hashable, tuple[float, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cached(key: Hashable) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None or entry[0] <= time.monotonic():
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return entry[1]


def _remember(key: Hashable, value: Any) -> Any:
    with _cache_lock:
        _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# --- plumbing -----------------------------------------------------------------


def _username(creds: Credentials) -> str:
    username = (creds.github_username or "").strip()
    if not username:
        raise GitHubNotConfiguredError(
            "Your GitHub username is required (set it in Settings)"
        )
    return username


def _client(creds: Credentials) -> CorpusGitHubClient:
    return CorpusGitHubClient(creds.secret(GITHUB_TOKEN) or None)


async def _with_client(
    creds: Credentials, fn: Callable[[CorpusGitHubClient], Awaitable[T]]
) -> T:
    """Run ``fn`` on a client built from the caller's token, translating the
    client's errors into this module's."""
    client = _client(creds)
    try:
        return await fn(client)
    # The base client (services/github.py) raises ValueError for a 404 or a
    # 403, the corpus client its own GitHubAPIError: same wording, same map.
    except (GitHubAPIError, ValueError) as exc:
        message = str(exc)
        if "rate limit" in message:
            raise GitHubRateLimitError(message) from exc
        if "not found" in message:
            raise GitHubNotFoundError(message) from exc
        raise GitHubUnavailableError(message) from exc
    except httpx.HTTPError as exc:
        raise GitHubUnavailableError(f"GitHub did not answer: {exc}") from exc
    finally:
        await client.close()


def _own_repo(creds: Credentials, owner: str) -> str:
    """The configured username, which ``owner`` must be: this browses your
    own account, it is not a GitHub proxy."""
    username = _username(creds)
    if owner.lower() != username.lower():
        raise GitHubNotFoundError(f"'{owner}' is not your GitHub account ({username})")
    return username


async def _refuse_private(client: CorpusGitHubClient, owner: str, name: str) -> None:
    """Public repos only, checked before any other read of the repo (see the
    module docstring)."""
    if not await client.is_public(owner, name):
        raise GitHubNotFoundError(
            f"'{owner}/{name}' is not public: this page shows public repos only"
        )


def _iso(epoch: int) -> Optional[str]:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


def _repo_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    fork = bool(data.get("fork"))
    archived = bool(data.get("archived"))
    return {
        "name": data.get("name") or "",
        "full_name": data.get("full_name") or "",
        "description": data.get("description") or None,
        "language": data.get("language") or None,
        "stars": int(data.get("stargazers_count") or 0),
        "topics": list(data.get("topics") or []),
        "fork": fork,
        "archived": archived,
        # What the Q&A job takes: public, not a fork, not archived.
        "eligible": not fork and not archived and not data.get("private"),
        "pushed_at": data.get("pushed_at"),
        "html_url": data.get("html_url") or "",
        "homepage": data.get("homepage") or None,
        "default_branch": data.get("default_branch") or "main",
    }


def _is_doc(entry: Dict[str, Any]) -> bool:
    path = str(entry.get("path") or "")
    return (
        entry.get("type") == "blob"
        and path.lower().startswith("docs/")
        and path.lower().endswith(DOC_EXTENSIONS)
    )


def valid_doc_path(path: str) -> bool:
    """A ``docs/`` markdown path the generation could read, nothing else."""
    lower = path.lower()
    return (
        0 < len(path) <= MAX_DOC_PATH_CHARS
        and lower.startswith("docs/")
        and lower.endswith(DOC_EXTENSIONS)
        and ".." not in path.split("/")
        and not path.startswith("/")
    )


# --- reads -------------------------------------------------------------------


async def profile(creds: Credentials) -> Dict[str, Any]:
    """Your account, and how much of the API quota is left."""
    username = _username(creds)
    key = ("profile", username, bool(creds.has(GITHUB_TOKEN)))
    cached = _cached(key)
    if cached is not None:
        return cached

    async def read(client: CorpusGitHubClient) -> Dict[str, Any]:
        user = await client.fetch_profile(username)
        quota = await client.rate_limit()
        return {
            "login": user.login,
            "name": user.name or None,
            "bio": user.bio or None,
            "company": user.company or None,
            "location": user.location or None,
            "blog": user.blog or None,
            "html_url": user.html_url,
            "avatar_url": user.avatar_url or None,
            "public_repos": user.public_repos,
            "followers": user.followers,
            "following": user.following,
            "rate_limit": {
                "limit": quota["limit"],
                "remaining": quota["remaining"],
                "reset_at": _iso(quota["reset"]),
                "authenticated": creds.has(GITHUB_TOKEN),
            },
        }

    return _remember(key, await _with_client(creds, read))


async def list_repos(creds: Credentials) -> Dict[str, Any]:
    """Your public repos, most recently updated first."""
    username = _username(creds)
    key = ("repos", username)
    cached = _cached(key)
    if cached is not None:
        return cached

    async def read(client: CorpusGitHubClient) -> Dict[str, Any]:
        repos = [_repo_summary(r) for r in await client.list_public_repos(username)]
        return {"username": username, "total": len(repos), "repos": repos}

    return _remember(key, await _with_client(creds, read))


async def repo_detail(creds: Credentials, owner: str, name: str) -> Dict[str, Any]:
    """One repo as a generation sees it: README, docs, stack, overview text."""
    username = _own_repo(creds, owner)
    key = ("repo", username, name.lower())
    cached = _cached(key)
    if cached is not None:
        return cached

    async def read(client: CorpusGitHubClient) -> Dict[str, Any]:
        await _refuse_private(client, username, name)
        repo: RepoData = await client.fetch_repo(username, name)
        branch = await client.default_branch(username, name)
        try:
            tree = await client.repo_tree(username, name, branch)
        except GitHubAPIError as exc:
            logger.warning("docs/ tree of %s/%s unavailable: %s", username, name, exc)
            tree = []
        docs = []
        for entry in tree:
            if not _is_doc(entry):
                continue
            size = int(entry.get("size") or 0)
            docs.append(
                {
                    "path": entry["path"],
                    "size": size,
                    # Over the job's size cap: skipped by a generation.
                    "readable": size <= MAX_DOC_BYTES,
                    "selected_by_default": False,
                }
            )
        # The job reads the first readable files, in tree order, up to its cap.
        taken = 0
        for doc in docs:
            if doc["readable"] and taken < MAX_DOCS_PER_REPO:
                doc["selected_by_default"] = True
                taken += 1
        return {
            "name": repo.name,
            "full_name": f"{username}/{repo.name}",
            "description": repo.description or None,
            "stars": repo.stars,
            "topics": repo.topics,
            "language": repo.language or None,
            "homepage": repo.homepage or None,
            "html_url": repo.url,
            "default_branch": branch,
            "readme": repo.readme or None,
            "readme_truncated": repo.readme.endswith("[README truncated]"),
            "technologies": repo.technologies,
            "docs": docs,
            "model_input": overview_context(repo),
            "limits": {
                "readme_chars": MAX_README_CHARS,
                "doc_chars": MAX_DOC_CHARS,
                "doc_bytes": MAX_DOC_BYTES,
                "docs_per_repo": MAX_DOCS_PER_REPO,
            },
        }

    return _remember(key, await _with_client(creds, read))


async def doc_content(
    creds: Credentials, owner: str, name: str, path: str
) -> Dict[str, Any]:
    """A ``docs/`` file as the model would read it (cut at the job's cap)."""
    username = _own_repo(creds, owner)
    if not valid_doc_path(path):
        raise GitHubNotFoundError("Only Markdown or text files under docs/ can be read")
    key = ("doc", username, name.lower(), path)
    cached = _cached(key)
    if cached is not None:
        return cached

    async def read(client: CorpusGitHubClient) -> Dict[str, Any]:
        await _refuse_private(client, username, name)
        content = await client.file_content(username, name, path)
        truncated = len(content) > MAX_DOC_CHARS
        if truncated:
            content = f"{content[:MAX_DOC_CHARS]}\n[...truncated]"
        return {
            "path": path,
            "content": content,
            "truncated": truncated,
            "max_chars": MAX_DOC_CHARS,
        }

    return _remember(key, await _with_client(creds, read))


__all__: List[str] = [
    "GitHubNotConfiguredError",
    "GitHubNotFoundError",
    "GitHubRateLimitError",
    "GitHubUnavailableError",
    "clear_cache",
    "doc_content",
    "list_repos",
    "profile",
    "repo_detail",
    "valid_doc_path",
]
