"""The GitHub browse routes (api/github.py): service errors out as HTTP answers."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import github as github_api
from server.api.deps import get_credentials
from server.services import github_browse as browse
from server.tests.creds import make_creds

CREDS = make_creds(github_username="kevin")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(github_api.router)
    app.dependency_overrides[get_credentials] = lambda: CREDS
    return TestClient(app)


def test_repos_pass_through(client):
    listing = {"username": "kevin", "total": 0, "repos": []}
    with patch.object(
        browse, "list_repos", new=AsyncMock(return_value=listing)
    ) as repos:
        response = client.get("/github/repos")

    assert response.status_code == 200 and response.json() == listing
    repos.assert_awaited_once_with(CREDS)


def test_doc_passes_the_path(client):
    doc = {"path": "docs/a.md", "content": "x", "truncated": False, "max_chars": 3000}
    with patch.object(
        browse, "doc_content", new=AsyncMock(return_value=doc)
    ) as content:
        response = client.get(
            "/github/repos/kevin/alpha/doc", params={"path": "docs/a.md"}
        )

    assert response.status_code == 200
    content.assert_awaited_once_with(CREDS, "kevin", "alpha", "docs/a.md")


@pytest.mark.parametrize(
    "error,status",
    [
        (browse.GitHubNotConfiguredError("Your GitHub username is required"), 400),
        (browse.GitHubNotFoundError("'x' is not your GitHub account"), 404),
        (browse.GitHubRateLimitError("GitHub rate limit exhausted"), 429),
    ],
)
def test_service_errors_map_to_http(client, error, status):
    with patch.object(browse, "repo_detail", new=AsyncMock(side_effect=error)):
        response = client.get("/github/repos/kevin/alpha")

    assert response.status_code == status
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize(
    "error",
    [
        browse.GitHubUnavailableError("https://api.internal/x failed"),
        RuntimeError("secret"),
    ],
)
def test_failures_do_not_leak_internals(client, error):
    with patch.object(browse, "profile", new=AsyncMock(side_effect=error)):
        response = client.get("/github/profile")

    assert response.status_code == 502
    assert "internal" not in response.text and "secret" not in response.text


def test_doc_needs_a_path(client):
    assert client.get("/github/repos/kevin/alpha/doc").status_code == 422
