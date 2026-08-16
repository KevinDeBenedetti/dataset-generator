"""Fetch public documentation from a GitHub account for dataset generation.

Scope: a user's public repositories, mined for each repo's README plus its
top-level documentation files (markdown / text). The token is optional and used
only to raise the API rate limit — only public information is ever read.
"""

import asyncio
import logging
from typing import List, Optional, Tuple

import httpx

GITHUB_API = "https://api.github.com"
# Top-level doc files worth mining (README is fetched separately via its endpoint).
DOC_EXTENSIONS = (".md", ".markdown", ".txt", ".rst")
_README_NAMES = {"readme.md", "readme.markdown", "readme.txt", "readme.rst", "readme"}

# (label, text) for one fetched document.
DocChunk = Tuple[str, str]

# Repos are mined concurrently (capped) instead of one after another — a
# sequential scan of a large account made `fetch_account_docs` the slowest
# step of the GitHub pipeline. Capped well under GitHub's per-hour rate limit
# so a big account doesn't burst through it in a few seconds.
_DEFAULT_CONCURRENCY = 5


class GitHubService:
    """Thin async GitHub REST client scoped to public read access."""

    def __init__(self, token: Optional[str] = None, timeout: float = 30.0):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(
            base_url=GITHUB_API, headers=headers, timeout=timeout
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def list_public_repos(
        self, username: str, max_repos: Optional[int] = None
    ) -> List[dict]:
        """Return the user's owned public repos (paginated, most-recent first)."""
        repos: List[dict] = []
        page = 1
        while True:
            resp = await self.client.get(
                f"/users/{username}/repos",
                params={
                    "per_page": 100,
                    "page": page,
                    "type": "owner",
                    "sort": "updated",
                },
            )
            if resp.status_code == 404:
                raise ValueError(f"GitHub user '{username}' not found")
            if resp.status_code == 403:
                raise ValueError(
                    "GitHub API rate limit reached or access forbidden — "
                    "provide a token to raise the limit."
                )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            repos.extend(batch)
            if max_repos and len(repos) >= max_repos:
                return repos[:max_repos]
            if len(batch) < 100:
                break
            page += 1
        return repos

    async def get_readme(self, owner: str, repo: str) -> Optional[str]:
        """Return the repo's README as raw text, or None if it has none."""
        resp = await self.client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    async def list_top_level_docs(self, owner: str, repo: str) -> List[dict]:
        """List top-level documentation files (excluding the README)."""
        resp = await self.client.get(f"/repos/{owner}/{repo}/contents")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return []
        return [
            it
            for it in items
            if it.get("type") == "file"
            and it.get("name", "").lower().endswith(DOC_EXTENSIONS)
            and it.get("name", "").lower() not in _README_NAMES
        ]

    async def get_file_text(self, item: dict) -> Optional[str]:
        """Fetch a content item's raw text via its download URL."""
        url = item.get("download_url")
        if not url:
            return None
        resp = await self.client.get(url)
        if resp.status_code != 200:
            return None
        return resp.text


async def _fetch_repo_docs(
    svc: GitHubService, owner: str, name: str, semaphore: asyncio.Semaphore
) -> List[DocChunk]:
    """README + top-level docs for one repo, or [] if the repo errors out."""
    async with semaphore:
        chunks: List[DocChunk] = []
        try:
            readme = await svc.get_readme(owner, name)
            if readme and readme.strip():
                chunks.append((f"{owner}/{name}:README", readme))

            for item in await svc.list_top_level_docs(owner, name):
                text = await svc.get_file_text(item)
                if text and text.strip():
                    chunks.append((f"{owner}/{name}:{item['name']}", text))
        except httpx.HTTPError as exc:
            # One bad repo shouldn't abort the whole account.
            logging.warning("Skipping %s/%s: %s", owner, name, exc)
        return chunks


async def fetch_account_docs(
    username: str,
    token: Optional[str] = None,
    max_repos: Optional[int] = None,
    include_archived: bool = False,
    max_concurrency: int = _DEFAULT_CONCURRENCY,
) -> List[DocChunk]:
    """Collect README + top-level docs across a user's public repositories.

    Repos are mined concurrently (bounded by ``max_concurrency``). Returns a
    list of ``(label, text)`` chunks in the same order as the repo listing
    (most-recently-updated first), regardless of fetch completion order.
    Raises ``ValueError`` if the user does not exist or the API rejects the
    request.
    """
    svc = GitHubService(token)
    try:
        repos = await svc.list_public_repos(username, max_repos=max_repos)
        semaphore = asyncio.Semaphore(max_concurrency)
        tasks = []
        for repo in repos:
            if repo.get("private"):
                continue
            if repo.get("archived") and not include_archived:
                continue
            owner = (repo.get("owner") or {}).get("login") or username
            name = repo.get("name")
            if not name:
                continue
            tasks.append(_fetch_repo_docs(svc, owner, name, semaphore))

        results = await asyncio.gather(*tasks)
    finally:
        await svc.close()

    chunks: List[DocChunk] = []
    for repo_chunks in results:
        chunks.extend(repo_chunks)
    return chunks
