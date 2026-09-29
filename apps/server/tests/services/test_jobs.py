from unittest.mock import AsyncMock, patch

import pytest

from server.jobs.corpus import JobError as CorpusJobError
from server.services.jobs import jobs_status, run_corpus_sync, run_qa_dataset_sync


def test_jobs_status_reports_missing_config(monkeypatch):
    for var in (
        "GITHUB_USERNAME",
        "GITHUB_TOKEN",
        "HF_TOKEN",
        "HF_DATASET_REPO",
        "HF_QA_DATASET_REPO",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    status = jobs_status()
    assert status["corpus"] == {
        "configured": False,
        "github_username": False,
        "github_token": False,
        "hf_token": False,
        "hf_dataset_repo": False,
    }
    assert status["qa_dataset"]["configured"] is False
    assert status["qa_dataset"]["claude_credentials"] is False


def test_jobs_status_reports_fully_configured(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("GITHUB_TOKEN", "gh")
    monkeypatch.setenv("HF_TOKEN", "hf")
    monkeypatch.setenv("HF_DATASET_REPO", "ns/corpus")
    monkeypatch.setenv("HF_QA_DATASET_REPO", "ns/qa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    status = jobs_status()
    assert status["corpus"]["configured"] is True
    assert status["qa_dataset"]["configured"] is True
    assert status["qa_dataset"]["claude_credentials"] is True


async def test_run_corpus_sync_rejects_unknown_source(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    with pytest.raises(CorpusJobError, match="unknown source"):
        await run_corpus_sync(["bogus"], dry_run=True)


async def test_run_corpus_sync_requires_github_username(monkeypatch):
    monkeypatch.delenv("GITHUB_USERNAME", raising=False)
    with pytest.raises(CorpusJobError, match="GITHUB_USERNAME"):
        await run_corpus_sync(None, dry_run=True)


async def test_run_corpus_sync_dry_run_skips_push(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("HF_DATASET_REPO", "ns/corpus")
    manifest = {"files": []}
    with (
        patch(
            "server.services.jobs.corpus_job.export_corpus",
            new=AsyncMock(return_value=manifest),
        ) as export,
        patch("server.services.jobs.corpus_job.push_corpus") as push,
    ):
        result = await run_corpus_sync(["profile"], dry_run=True)

    assert result == {"manifest": manifest, "url": None, "dry_run": True}
    export.assert_awaited_once()
    assert export.call_args.args[1] == ["profile"]
    push.assert_not_called()


async def test_run_corpus_sync_pushes_when_not_dry_run(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("HF_DATASET_REPO", "ns/corpus")
    manifest = {"files": [{"source": "profile"}]}
    with (
        patch(
            "server.services.jobs.corpus_job.export_corpus",
            new=AsyncMock(return_value=manifest),
        ),
        patch(
            "server.services.jobs.corpus_job.push_corpus",
            return_value="https://huggingface.co/datasets/ns/corpus",
        ) as push,
    ):
        result = await run_corpus_sync(None, dry_run=False)

    assert result == {
        "manifest": manifest,
        "url": "https://huggingface.co/datasets/ns/corpus",
        "dry_run": False,
    }
    push.assert_called_once()


async def test_run_corpus_sync_requires_hf_repo_to_push(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    with (
        patch(
            "server.services.jobs.corpus_job.export_corpus",
            new=AsyncMock(return_value={"files": []}),
        ),
        patch("server.services.jobs.corpus_job.push_corpus") as push,
    ):
        with pytest.raises(CorpusJobError, match="HF_DATASET_REPO"):
            await run_corpus_sync(None, dry_run=False)
    push.assert_not_called()


async def test_run_qa_dataset_sync_delegates_to_the_job(monkeypatch):
    with patch(
        "server.services.jobs.qa_dataset_job.run",
        new=AsyncMock(return_value={"records": 1}),
    ) as run:
        result = await run_qa_dataset_sync(3, True)

    assert result == {"records": 1}
    run.assert_awaited_once_with(max_repos=3, dry_run=True)
