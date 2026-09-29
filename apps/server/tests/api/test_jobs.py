"""Tests for the /jobs API endpoints.

Thin wrappers over server.services.jobs, so these mock that service and
assert the HTTP contract (status + shape / error mapping).
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.jobs.corpus import JobError as CorpusJobError
from server.jobs.qa_dataset import JobError as QADatasetJobError


def test_get_jobs_status(client: TestClient):
    status = {
        "corpus": {
            "configured": True,
            "github_username": True,
            "github_token": True,
            "hf_token": True,
            "hf_dataset_repo": True,
        },
        "qa_dataset": {
            "configured": False,
            "github_username": True,
            "github_token": True,
            "claude_credentials": False,
            "hf_token": True,
            "hf_qa_dataset_repo": False,
        },
    }
    with patch("server.api.jobs.jobs_status", return_value=status):
        response = client.get("/jobs/status")
    assert response.status_code == 200
    assert response.json() == status


def test_trigger_corpus_sync_success(client: TestClient):
    result = {
        "manifest": {"files": [{"source": "profile", "records": 4}]},
        "url": "https://huggingface.co/datasets/ns/corpus",
        "dry_run": False,
    }
    with patch(
        "server.api.jobs.run_corpus_sync", new=AsyncMock(return_value=result)
    ) as run:
        response = client.post(
            "/jobs/corpus-sync", json={"sources": ["profile"], "dry_run": False}
        )
    assert response.status_code == 200
    assert response.json() == result
    run.assert_awaited_once_with(["profile"], False)


def test_trigger_corpus_sync_bad_request_on_job_error(client: TestClient):
    with patch(
        "server.api.jobs.run_corpus_sync",
        new=AsyncMock(side_effect=CorpusJobError('unknown source "bogus"')),
    ):
        response = client.post("/jobs/corpus-sync", json={"sources": ["bogus"]})
    assert response.status_code == 400
    assert "bogus" in response.json()["detail"]


def test_trigger_corpus_sync_defaults_to_all_sources(client: TestClient):
    result = {"manifest": {}, "url": None, "dry_run": True}
    with patch(
        "server.api.jobs.run_corpus_sync", new=AsyncMock(return_value=result)
    ) as run:
        response = client.post("/jobs/corpus-sync", json={})
    assert response.status_code == 200
    run.assert_awaited_once_with(None, False)


def test_trigger_corpus_sync_maps_unexpected_errors_to_502(client: TestClient):
    with patch(
        "server.api.jobs.run_corpus_sync",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = client.post("/jobs/corpus-sync", json={})
    assert response.status_code == 502


def test_trigger_qa_dataset_sync_success(client: TestClient):
    result = {
        "repo": "ns/qa",
        "url": "https://huggingface.co/datasets/ns/qa",
        "records": 12,
        "dropped": 1,
        "errors": [],
        "dry_run": False,
    }
    with patch(
        "server.api.jobs.run_qa_dataset_sync", new=AsyncMock(return_value=result)
    ) as run:
        response = client.post(
            "/jobs/qa-dataset-sync", json={"max_repos": 2, "dry_run": False}
        )
    assert response.status_code == 200
    assert response.json() == result
    run.assert_awaited_once_with(2, False)


def test_trigger_qa_dataset_sync_bad_request_on_job_error(client: TestClient):
    with patch(
        "server.api.jobs.run_qa_dataset_sync",
        new=AsyncMock(side_effect=QADatasetJobError("HF_TOKEN is required")),
    ):
        response = client.post("/jobs/qa-dataset-sync", json={})
    assert response.status_code == 400
    assert "HF_TOKEN" in response.json()["detail"]


def test_trigger_qa_dataset_sync_rejects_non_positive_max_repos(client: TestClient):
    response = client.post("/jobs/qa-dataset-sync", json={"max_repos": 0})
    assert response.status_code == 422
