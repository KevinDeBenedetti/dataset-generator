import base64
import json
from typing import Callable, Dict
from unittest.mock import patch

import httpx
import pytest

from server.jobs.github_snapshot import (
    CorpusGitHubClient,
    GitHubProfile,
    GitHubSnapshot,
    RepoData,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class FakeGitHub:
    """Routes GitHub API paths to canned JSON/text responses."""

    def __init__(self) -> None:
        self.routes: Dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[str] = []

    def json(self, path: str, data, status: int = 200, headers=None) -> None:
        self.routes[path] = lambda _req: httpx.Response(
            status, content=json.dumps(data), headers=headers or {}
        )

    def text(self, path: str, text: str) -> None:
        self.routes[path] = lambda _req: httpx.Response(200, text=text)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        route = self.routes.get(path)
        return route(request) if route else httpx.Response(404, json={})

    def client(self) -> CorpusGitHubClient:
        real = httpx.AsyncClient
        transport = httpx.MockTransport(self.handler)

        def mocked(**kwargs):
            return real(transport=transport, trust_env=False, **kwargs)

        with patch("server.services.github.httpx.AsyncClient", side_effect=mocked):
            return CorpusGitHubClient("tok")


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def snapshot() -> GitHubSnapshot:
    return GitHubSnapshot(
        username="kevin",
        profile=GitHubProfile(
            login="kevin",
            name="Kevin De Benedetti",
            bio="Dev",
            company="Acme",
            location="Lyon",
            email="k@example.com",
            blog="https://kevindb.dev",
            twitter="kdb",
            public_repos=12,
            followers=34,
            following=5,
            html_url="https://github.com/kevin",
        ),
        repos=[
            RepoData(
                name="portfolio",
                description="My site",
                stars=7,
                topics=["go", "next"],
                language="Go",
                homepage="https://kevindb.dev",
                url="https://github.com/kevin/portfolio",
                readme="# Portfolio\nHello",
            )
        ],
        fetched_at="2026-09-15T00:00:00Z",
    )
