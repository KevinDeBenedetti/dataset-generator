"""Tests for the GitHub public-docs ingestion service."""

from unittest.mock import MagicMock, patch

import pytest

from server.services.github import fetch_account_docs


def _resp(status=200, json_data=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def _client_with(dispatch):
    client = MagicMock()
    client.get.side_effect = dispatch
    return client


@patch("server.services.github.httpx.Client")
def test_collects_readme_and_top_level_docs(mock_client_class):
    def dispatch(path, **kwargs):
        if path == "/users/octocat/repos":
            return _resp(
                json_data=[
                    {
                        "name": "repo1",
                        "owner": {"login": "octocat"},
                        "private": False,
                        "archived": False,
                    }
                ]
            )
        if path == "/repos/octocat/repo1/readme":
            return _resp(text="# Repo1 README")
        if path == "/repos/octocat/repo1/contents":
            return _resp(
                json_data=[
                    {
                        "type": "file",
                        "name": "GUIDE.md",
                        "download_url": "https://raw/GUIDE.md",
                    },
                    # Not a doc file → ignored.
                    {
                        "type": "file",
                        "name": "script.py",
                        "download_url": "https://raw/script.py",
                    },
                    {"type": "dir", "name": "src"},
                ]
            )
        if path == "https://raw/GUIDE.md":
            return _resp(text="Guide content")
        raise AssertionError(f"unexpected path {path}")

    mock_client_class.return_value = _client_with(dispatch)

    chunks = fetch_account_docs("octocat")
    as_dict = dict(chunks)
    assert as_dict["octocat/repo1:README"] == "# Repo1 README"
    assert as_dict["octocat/repo1:GUIDE.md"] == "Guide content"
    assert len(chunks) == 2  # script.py is not a doc extension


@patch("server.services.github.httpx.Client")
def test_unknown_user_raises_value_error(mock_client_class):
    def dispatch(path, **kwargs):
        if path == "/users/ghost/repos":
            return _resp(status=404)
        raise AssertionError(f"unexpected path {path}")

    mock_client_class.return_value = _client_with(dispatch)

    with pytest.raises(ValueError, match="not found"):
        fetch_account_docs("ghost")


@patch("server.services.github.httpx.Client")
def test_skips_archived_and_private_repos(mock_client_class):
    def dispatch(path, **kwargs):
        if path == "/users/octocat/repos":
            return _resp(
                json_data=[
                    {
                        "name": "active",
                        "owner": {"login": "octocat"},
                        "private": False,
                        "archived": False,
                    },
                    {
                        "name": "old",
                        "owner": {"login": "octocat"},
                        "private": False,
                        "archived": True,
                    },
                    {
                        "name": "secret",
                        "owner": {"login": "octocat"},
                        "private": True,
                        "archived": False,
                    },
                ]
            )
        if path == "/repos/octocat/active/readme":
            return _resp(text="active readme")
        if path == "/repos/octocat/active/contents":
            return _resp(json_data=[])
        raise AssertionError(f"unexpected path {path}")

    mock_client_class.return_value = _client_with(dispatch)

    chunks = fetch_account_docs("octocat")
    assert [label for label, _ in chunks] == ["octocat/active:README"]


@patch("server.services.github.httpx.Client")
def test_repo_without_readme_still_collects_docs(mock_client_class):
    def dispatch(path, **kwargs):
        if path == "/users/octocat/repos":
            return _resp(
                json_data=[
                    {
                        "name": "repo1",
                        "owner": {"login": "octocat"},
                        "private": False,
                        "archived": False,
                    }
                ]
            )
        if path == "/repos/octocat/repo1/readme":
            return _resp(status=404)  # no README
        if path == "/repos/octocat/repo1/contents":
            return _resp(
                json_data=[
                    {
                        "type": "file",
                        "name": "NOTES.txt",
                        "download_url": "https://raw/NOTES.txt",
                    }
                ]
            )
        if path == "https://raw/NOTES.txt":
            return _resp(text="some notes")
        raise AssertionError(f"unexpected path {path}")

    mock_client_class.return_value = _client_with(dispatch)

    chunks = fetch_account_docs("octocat")
    assert [label for label, _ in chunks] == ["octocat/repo1:NOTES.txt"]
