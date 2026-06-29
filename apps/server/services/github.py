"""Fetch public documentation from a GitHub account for dataset generation.

Scope: a user's public repositories, mined for each repo's README plus its
top-level documentation files (markdown / text). The token is optional and used
only to raise the API rate limit — only public information is ever read.
"""

import logging
from typing import List, Optional, Tuple

import httpx

GITHUB_API = "https://api.github.com"
# Top-level doc files worth mining (README is fetched separately via its endpoint).
DOC_EXTENSIONS = (".md", ".markdown", ".txt", ".rst")
_README_NAMES = {"readme.md", "readme.markdown", "readme.txt", "readme.rst", "readme"}

# (label, text) for one fetched document.
DocChunk = Tuple[str, str]


class GitHubService:
    """Thin GitHub REST client scoped to public read access."""

    def __init__(self, token: Optional[str] = None, timeout: float = 30.0):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(
            base_url=GITHUB_API, headers=headers, timeout=timeout
        )

    def close(self) -> None:
        self.client.close()

    def list_public_repos(
        self, username: str, max_repos: Optional[int] = None
    ) -> List[dict]:
        """Return the user's owned public repos (paginated, most-recent first)."""
        repos: List[dict] = []
        page = 1
        while True:
            resp = self.client.get(
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

    def get_readme(self, owner: str, repo: str) -> Optional[str]:
        """Return the repo's README as raw text, or None if it has none."""
        resp = self.client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def list_top_level_docs(self, owner: str, repo: str) -> List[dict]:
        """List top-level documentation files (excluding the README)."""
        resp = self.client.get(f"/repos/{owner}/{repo}/contents")
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

    def get_file_text(self, item: dict) -> Optional[str]:
        """Fetch a content item's raw text via its download URL."""
        url = item.get("download_url")
        if not url:
            return None
        resp = self.client.get(url)
        if resp.status_code != 200:
            return None
        return resp.text


def fetch_account_docs(
    username: str,
    token: Optional[str] = None,
    max_repos: Optional[int] = None,
    include_archived: bool = False,
) -> List[DocChunk]:
    """Collect README + top-level docs across a user's public repositories.

    Returns a list of ``(label, text)`` chunks (one per document). Raises
    ``ValueError`` if the user does not exist or the API rejects the request.
    """
    svc = GitHubService(token)
    chunks: List[DocChunk] = []
    try:
        repos = svc.list_public_repos(username, max_repos=max_repos)
        for repo in repos:
            if repo.get("private"):
                continue
            if repo.get("archived") and not include_archived:
                continue
            owner = (repo.get("owner") or {}).get("login") or username
            name = repo.get("name")
            if not name:
                continue

            try:
                readme = svc.get_readme(owner, name)
                if readme and readme.strip():
                    chunks.append((f"{owner}/{name}:README", readme))

                for item in svc.list_top_level_docs(owner, name):
                    text = svc.get_file_text(item)
                    if text and text.strip():
                        chunks.append((f"{owner}/{name}:{item['name']}", text))
            except httpx.HTTPError as exc:
                # One bad repo shouldn't abort the whole account.
                logging.warning("Skipping %s/%s: %s", owner, name, exc)
                continue
    finally:
        svc.close()
    return chunks
