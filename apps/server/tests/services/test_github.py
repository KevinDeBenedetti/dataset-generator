"""Tests for the thin GitHub REST client the scheduled jobs build on."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.services.github import GitHubService


def _resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def _client_with(dispatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=dispatch)
    client.aclose = AsyncMock()
    return client


@patch("server.services.github.httpx.AsyncClient")
async def test_token_sets_the_authorization_header(mock_client_class):
    GitHubService("tok")
    headers = mock_client_class.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer tok"


@patch("server.services.github.httpx.AsyncClient")
async def test_list_public_repos_paginates_and_caps(mock_client_class):
    pages = {1: [{"name": f"r{i}"} for i in range(100)], 2: [{"name": "last"}]}

    def dispatch(path, params, **kwargs):
        assert path == "/users/octocat/repos"
        return _resp(json_data=pages.get(params["page"], []))

    mock_client_class.return_value = _client_with(dispatch)
    svc = GitHubService()

    repos = await svc.list_public_repos("octocat")
    assert len(repos) == 101 and repos[-1]["name"] == "last"
    assert len(await svc.list_public_repos("octocat", max_repos=5)) == 5


@pytest.mark.parametrize("status, match", [(404, "not found"), (403, "rate limit")])
@patch("server.services.github.httpx.AsyncClient")
async def test_list_public_repos_errors(mock_client_class, status, match):
    mock_client_class.return_value = _client_with(lambda *a, **k: _resp(status=status))
    with pytest.raises(ValueError, match=match):
        await GitHubService().list_public_repos("ghost")


@patch("server.services.github.httpx.AsyncClient")
async def test_get_readme(mock_client_class):
    def dispatch(path, **kwargs):
        if path == "/repos/o/has/readme":
            return _resp(text="# README")
        return _resp(status=404)

    mock_client_class.return_value = _client_with(dispatch)
    svc = GitHubService()
    assert await svc.get_readme("o", "has") == "# README"
    assert await svc.get_readme("o", "none") is None
