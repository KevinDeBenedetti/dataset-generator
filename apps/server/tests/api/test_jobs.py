"""Tests for the /jobs API endpoints.

Thin wrappers over server.services.jobs, so these mock that service and
assert the HTTP contract (status + shape / error mapping).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.jobs.qa_dataset import JobError as QADatasetJobError
from server.services.jobs import RunConflictError, UnknownJobError, UnknownRunError

RUN = {
    "id": "run-1",
    "job": "github-personal",
    "status": "running",
    "options": {"max_repos": 2},
    "model_ref": "openai:gpt-x",
    "started_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
    "progress": {"done": 1, "total": 4, "label": "repo-a"},
    "has_draft": False,
}


def test_get_jobs(client: TestClient):
    jobs = [
        {
            "id": "github-personal",
            "title": "GitHub personal Q&A",
            "description": "…",
            "workflow": "qa-dataset-sync.yml",
            "schedule": "Mondays 06:00 UTC",
            "uses_model": True,
            "default_model": "claude:claude-sonnet-5",
            "has_draft": True,
            "configured": False,
            "missing_env": ["HF_TOKEN"],
            "options_schema": {"type": "object", "properties": {}},
            "latest_run": {"id": "run-1", "status": "succeeded"},
        }
    ]
    with patch("server.api.jobs.list_jobs", return_value=jobs):
        response = client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == {"jobs": jobs}


def test_start_run_is_accepted(client: TestClient):
    with patch("server.api.jobs.start_run", new=AsyncMock(return_value=RUN)) as start:
        response = client.post(
            "/jobs/github-personal/run",
            json={"options": {"max_repos": 2}, "model_ref": "openai:gpt-x"},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["id"] == "run-1" and body["progress"]["label"] == "repo-a"
    start.assert_awaited_once_with("github-personal", {"max_repos": 2}, "openai:gpt-x")


def test_start_run_errors(client: TestClient):
    cases = [
        (UnknownJobError("nope"), 404),
        (RunConflictError("already running"), 409),
        (ValueError("Unknown model 'x:y'"), 400),
    ]
    for error, status in cases:
        with patch("server.api.jobs.start_run", new=AsyncMock(side_effect=error)):
            response = client.post("/jobs/github-personal/run", json={})
        assert response.status_code == status, error


def test_start_run_invalid_options_is_422(client: TestClient):
    response = client.post(
        "/jobs/github-personal/run", json={"options": {"max_repos": 0}}
    )
    assert response.status_code == 422


def test_get_run(client: TestClient):
    run = {
        **RUN,
        "status": "succeeded",
        "progress": None,
        "result": {"dry_run": True, "metrics": [["New", 2]], "errors": []},
        "has_draft": True,
        "preview": {
            "repo_id": "ns/qa",
            "kept": 5,
            "new": [{"id": "n1", "question": "Q?", "answer": "A.", "repo": "r"}],
            "review": [],
        },
    }
    with patch("server.api.jobs.get_run", return_value=run):
        response = client.get("/jobs/runs/run-1")
    assert response.status_code == 200
    body = response.json()
    assert body["preview"]["new"][0]["id"] == "n1"
    assert body["result"]["metrics"] == [["New", 2]]


def test_get_unknown_run_is_404(client: TestClient):
    with patch("server.api.jobs.get_run", side_effect=UnknownRunError("x")):
        assert client.get("/jobs/runs/x").status_code == 404


def test_publish_run(client: TestClient):
    published = {
        **RUN,
        "status": "published",
        "published_url": "https://huggingface.co/datasets/ns/qa",
    }
    with patch(
        "server.api.jobs.publish_run", new=AsyncMock(return_value=published)
    ) as publish:
        response = client.post(
            "/jobs/runs/run-1/publish", json={"exclude": ["n2"], "promote": ["h1"]}
        )
    assert response.status_code == 200
    assert response.json()["published_url"] == "https://huggingface.co/datasets/ns/qa"
    publish.assert_awaited_once_with("run-1", ["n2"], ["h1"])


def test_publish_errors(client: TestClient):
    cases = [
        (UnknownRunError("x"), 404),
        (RunConflictError("no draft"), 409),
        (QADatasetJobError("HF_TOKEN is required"), 400),
        (RuntimeError("hub down"), 502),
    ]
    for error, status in cases:
        with patch("server.api.jobs.publish_run", new=AsyncMock(side_effect=error)):
            response = client.post("/jobs/runs/run-1/publish", json={})
        assert response.status_code == status, error
