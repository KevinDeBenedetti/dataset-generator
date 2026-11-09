"""Tests for the GitHub browse reads (services/github_browse.py).

GitHub is never contacted: the client's HTTP layer is a ``MockTransport``
routing API paths to canned answers, which also records every request —
what the cache assertions are about.
"""

import base64
import json
from typing import Callable, Dict
from unittest.mock import patch

import httpx
import pytest

from server.jobs.github_snapshot import CorpusGitHubClient
from server.services import github_browse as browse
from server.tests.creds import make_creds

CREDS = make_creds(github_username="kevin", github_token="ghp_test")
ANONYMOUS = make_creds(github_username="kevin")


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class FakeGitHub:
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
        self.calls.append(request.url.path)
        route = self.routes.get(request.url.path)
        return route(request) if route else httpx.Response(404, json={})

    def client(self, token):
        real = httpx.AsyncClient
        transport = httpx.MockTransport(self.handler)

        def mocked(**kwargs):
            return real(transport=transport, trust_env=False, **kwargs)

        with patch("server.services.github.httpx.AsyncClient", side_effect=mocked):
            return CorpusGitHubClient(token)


@pytest.fixture
def github(monkeypatch) -> FakeGitHub:
    browse.clear_cache()
    fake = FakeGitHub()
    monkeypatch.setattr(
        browse,
        "_client",
        lambda creds: fake.client(creds.secret("github_token") or None),
    )
    fake.json(
        "/users/kevin",
        {
            "login": "kevin",
            "name": "Kevin",
            "bio": "Dev",
            "public_repos": 2,
            "followers": 3,
            "following": 1,
            "html_url": "https://github.com/kevin",
            "avatar_url": "https://avatars/kevin",
        },
    )
    fake.json(
        "/rate_limit",
        {
            "resources": {
                "core": {"limit": 5000, "remaining": 4990, "reset": 1_800_000_000}
            }
        },
    )
    fake.json(
        "/users/kevin/repos",
        [
            {
                "name": "alpha",
                "full_name": "kevin/alpha",
                "description": "A tool",
                "language": "Go",
                "stargazers_count": 7,
                "topics": ["cli"],
                "fork": False,
                "archived": False,
                "private": False,
                "pushed_at": "2026-10-01T00:00:00Z",
                "html_url": "https://github.com/kevin/alpha",
                "default_branch": "main",
            },
            {
                "name": "old",
                "full_name": "kevin/old",
                "fork": True,
                "archived": False,
                "stargazers_count": 0,
                "html_url": "https://github.com/kevin/old",
            },
        ],
    )
    fake.json(
        "/repos/kevin/alpha",
        {
            "name": "alpha",
            "description": "A tool",
            "stargazers_count": 7,
            "topics": ["cli"],
            "language": "Go",
            "html_url": "https://github.com/kevin/alpha",
            "default_branch": "main",
        },
    )
    fake.text(
        "/repos/kevin/alpha/readme",
        "# Alpha\n\n[![ci](https://img.shields.io/badge/x.svg)](x)\n\nA tool.",
    )
    fake.json(
        "/repos/kevin/alpha/git/trees/main",
        {
            "tree": [
                {"type": "blob", "path": "go.mod", "size": 40},
                {"type": "blob", "path": "docs/guide.md", "size": 120},
                {"type": "blob", "path": "docs/huge.md", "size": 10 * 1024 * 1024},
                {"type": "blob", "path": "docs/img.png", "size": 10},
                {"type": "tree", "path": "docs/api"},
                {"type": "blob", "path": "docs/api/ref.md", "size": 80},
            ]
        },
    )
    fake.json(
        "/repos/kevin/alpha/contents/go.mod",
        {
            "encoding": "base64",
            "content": b64("module alpha\n\nrequire github.com/gin-gonic/gin v1.9.0\n"),
        },
    )
    fake.json(
        "/repos/kevin/alpha/contents/docs/guide.md",
        {"encoding": "base64", "content": b64("# Guide\n\nHow to.")},
    )
    return fake


async def test_profile_needs_a_username():
    with pytest.raises(browse.GitHubNotConfiguredError, match="Settings"):
        await browse.profile(make_creds())


async def test_profile_with_quota(github):
    out = await browse.profile(CREDS)

    assert out["login"] == "kevin" and out["avatar_url"] == "https://avatars/kevin"
    assert out["rate_limit"] == {
        "limit": 5000,
        "remaining": 4990,
        "reset_at": "2027-01-15T08:00:00+00:00",
        "authenticated": True,
    }
    assert (await browse.profile(ANONYMOUS))["rate_limit"]["authenticated"] is False


async def test_repos_say_what_a_generation_takes(github):
    out = await browse.list_repos(CREDS)

    assert out["username"] == "kevin" and out["total"] == 2
    alpha, old = out["repos"]
    assert (
        alpha["eligible"] is True and alpha["stars"] == 7 and alpha["topics"] == ["cli"]
    )
    assert old["eligible"] is False and old["fork"] is True


async def test_repo_detail_is_what_the_model_sees(github):
    out = await browse.repo_detail(CREDS, "kevin", "alpha")

    # The README is cleaned (no badge) and the stack read from go.mod.
    assert out["readme"] == "# Alpha\n\nA tool."
    assert out["readme_truncated"] is False
    assert "Gin" in out["technologies"]
    assert out["model_input"].startswith("Repository: alpha")
    assert "README:\n# Alpha" in out["model_input"]
    # docs/: markdown only, readable size flagged, first ones picked by default.
    assert [
        (d["path"], d["readable"], d["selected_by_default"]) for d in out["docs"]
    ] == [
        ("docs/guide.md", True, True),
        ("docs/huge.md", False, False),
        ("docs/api/ref.md", True, True),
    ]
    assert out["limits"]["docs_per_repo"] == 6


async def test_repo_detail_is_cached(github):
    await browse.repo_detail(CREDS, "kevin", "alpha")
    calls = len(github.calls)

    await browse.repo_detail(CREDS, "kevin", "Alpha")

    assert len(github.calls) == calls


async def test_only_your_own_account(github):
    with pytest.raises(browse.GitHubNotFoundError, match="not your GitHub account"):
        await browse.repo_detail(CREDS, "someone-else", "alpha")


async def test_unknown_repo_is_not_found(github):
    with pytest.raises(browse.GitHubNotFoundError):
        await browse.repo_detail(CREDS, "kevin", "nope")


async def test_doc_content_is_cut_like_the_job(github, monkeypatch):
    monkeypatch.setattr(browse, "MAX_DOC_CHARS", 8)

    out = await browse.doc_content(CREDS, "kevin", "alpha", "docs/guide.md")

    assert out == {
        "path": "docs/guide.md",
        "content": "# Guide\n\n[...truncated]",
        "truncated": True,
        "max_chars": 8,
    }


@pytest.mark.parametrize(
    "path", ["README.md", "docs/../secret.md", "/docs/a.md", "docs/a.png", ""]
)
async def test_only_docs_files_can_be_read(github, path):
    with pytest.raises(browse.GitHubNotFoundError):
        await browse.doc_content(CREDS, "kevin", "alpha", path)
    assert not any(
        call.startswith("/repos/kevin/alpha/contents") for call in github.calls
    )


@pytest.fixture
def secret(github):
    """A private repo the owner's token can read."""
    github.json(
        "/repos/kevin/secret",
        {
            "name": "secret",
            "private": True,
            "visibility": "private",
            "default_branch": "main",
        },
    )
    github.text("/repos/kevin/secret/readme", "# Secret plans")
    github.json(
        "/repos/kevin/secret/contents/docs/plan.md",
        {"encoding": "base64", "content": b64("# Plan")},
    )
    return github


async def test_a_private_repo_is_never_read(secret):
    with pytest.raises(browse.GitHubNotFoundError, match="not public"):
        await browse.repo_detail(CREDS, "kevin", "secret")
    # Nothing past its visibility was asked for, so nothing could be cached.
    assert secret.calls == ["/repos/kevin/secret"]


async def test_a_private_repos_docs_are_never_read(secret):
    with pytest.raises(browse.GitHubNotFoundError, match="not public"):
        await browse.doc_content(CREDS, "kevin", "secret", "docs/plan.md")
    assert secret.calls == ["/repos/kevin/secret"]


async def test_the_same_username_without_a_token_gets_nothing_private(secret):
    # Refused for the owner's token first, so the per-username cache holds
    # nothing a caller without it could be served.
    with pytest.raises(browse.GitHubNotFoundError):
        await browse.repo_detail(CREDS, "kevin", "secret")
    with pytest.raises(browse.GitHubNotFoundError):
        await browse.repo_detail(ANONYMOUS, "kevin", "secret")
    with pytest.raises(browse.GitHubNotFoundError):
        await browse.doc_content(ANONYMOUS, "kevin", "secret", "docs/plan.md")
    assert not any("/readme" in c or "/contents/" in c for c in secret.calls)


@pytest.mark.parametrize(
    "meta",
    [{"private": True}, {"private": False, "visibility": "internal"}],
)
async def test_only_a_public_visibility_is_shown(github, meta):
    github.json("/repos/kevin/corp", {"name": "corp", **meta})
    with pytest.raises(browse.GitHubNotFoundError, match="not public"):
        await browse.repo_detail(CREDS, "kevin", "corp")


async def test_rate_limit_is_its_own_error(github):
    github.json(
        "/users/kevin/repos",
        {"message": "limit"},
        status=403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1800000000"},
    )

    with pytest.raises(browse.GitHubRateLimitError):
        await browse.list_repos(CREDS)
