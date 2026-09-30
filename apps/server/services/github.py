"""Thin GitHub REST client, public read access only.

The base the scheduled jobs build on (``server.jobs.github_snapshot``
extends it with tree/content/profile reads). The token is optional and only
raises the API rate limit — only public information is ever read.
"""

from typing import List, Optional

import httpx

GITHUB_API = "https://api.github.com"


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
