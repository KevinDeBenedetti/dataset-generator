"""The dataset job catalogue (server/jobs/registry.py) and the background run
service (server/services/jobs.py)."""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from server.jobs import qa_dataset
from server.jobs.corpus import JobError as CorpusJobError
from server.jobs.qa_dataset import Draft, QADataset, QAPair
from server.jobs.registry import (
    JOBS,
    GitHubPersonalOptions,
    JobOutcome,
    JobResult,
    KnowledgeCorpusOptions,
)
from server.services import jobs as jobs_service
from server.services.jobs import (
    RunConflictError,
    UnknownJobError,
    UnknownRunError,
    get_run,
    list_jobs,
    publish_run,
    start_run,
)

PREFIX = "server.jobs.registry"
JOB_ENV = ("GITHUB_USERNAME", "HF_TOKEN", "HF_QA_DATASET_REPO", "HF_DATASET_REPO")


def noop(done, total, label):
    pass


@pytest.fixture(autouse=True)
def jobs_model(monkeypatch):
    """The jobs role default, without a DB."""
    monkeypatch.setattr(
        "server.services.jobs.resolve_model",
        lambda role, override=None: override or "claude:claude-sonnet-5",
    )
    monkeypatch.setattr("server.services.jobs.validate_ref", lambda ref: ref)


def _job(jobs, job_id):
    return next(j for j in jobs if j["id"] == job_id)


def _draft():
    kept = QAPair("Kept question?", "Kept.", "overview", repo="r", id="k1")
    new1 = QAPair("New question one?", "One.", "docs", repo="r", id="n1")
    new2 = QAPair("New question two?", "Two.", "docs", repo="r", id="n2")
    held = QAPair("Held question?", "Far.", "docs", repo="r", id="h1", grounding=0.2)
    dataset = QADataset(
        [kept, new1, new2], 0, [], kept=1, new=2, review=[held], new_ids=["n1", "n2"]
    )
    return Draft(dataset, "kevin", "ns/qa", False, "claude:claude-sonnet-5")


# --- catalogue ------------------------------------------------------------------


def test_list_jobs_reports_missing_config(monkeypatch):
    for name in (*JOB_ENV, "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    jobs = list_jobs()
    assert {j["id"] for j in jobs} == {"github-personal", "knowledge-corpus"}
    personal = _job(jobs, "github-personal")
    assert personal["configured"] is False
    # The default model's provider credentials count too.
    assert personal["missing_env"] == [
        "GITHUB_USERNAME",
        "HF_TOKEN",
        "HF_QA_DATASET_REPO",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ]
    assert personal["uses_model"] and personal["has_draft"]
    corpus = _job(jobs, "knowledge-corpus")
    assert corpus["uses_model"] is False and corpus["has_draft"] is False


def test_list_jobs_serves_option_schemas(monkeypatch):
    for name in JOB_ENV:
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")

    jobs = list_jobs()
    assert all(j["configured"] for j in jobs)
    props = _job(jobs, "github-personal")["options_schema"]["properties"]
    # No dry run: generating always stops at a draft.
    assert set(props) == {"max_repos", "full_refresh"}
    corpus = _job(jobs, "knowledge-corpus")["options_schema"]["properties"]
    assert corpus["sources"]["items"]["enum"] == [
        "profile",
        "github",
        "github_code",
        "github_docs",
    ]


# --- github-personal ------------------------------------------------------------


async def test_github_personal_stops_at_a_draft():
    progress = []
    with patch(
        f"{PREFIX}.qa_dataset_job.generate", new=AsyncMock(return_value=_draft())
    ) as generate:
        outcome = await JOBS["github-personal"].runner(
            GitHubPersonalOptions(max_repos=2),
            "openai:gpt-x",
            lambda *a: progress.append(a),
        )

    kwargs = generate.call_args.kwargs
    assert (kwargs["max_repos"], kwargs["model_ref"]) == (2, "openai:gpt-x")
    assert callable(kwargs["on_progress"])
    assert outcome.result.dry_run is True and outcome.result.url is None
    assert dict(outcome.result.metrics)["New"] == 2
    assert outcome.draft is not None and outcome.draft["repo_id"] == "ns/qa"


def test_github_personal_preview_lists_new_and_review_pairs():
    preview_fn = JOBS["github-personal"].preview
    assert preview_fn is not None
    data = {
        "dataset": _draft().dataset.to_dict(),
        "username": "kevin",
        "repo_id": "ns/qa",
    }
    preview = preview_fn(data)
    assert preview["kept"] == 1 and preview["repo_id"] == "ns/qa"
    assert [p["id"] for p in preview["new"]] == ["n1", "n2"]
    assert [p["id"] for p in preview["review"]] == ["h1"]


async def test_github_personal_publishes_the_reviewed_selection():
    data = {
        "dataset": _draft().dataset.to_dict(),
        "username": "kevin",
        "repo_id": "ns/qa",
        "full_refresh": False,
        "model_ref": "claude:claude-sonnet-5",
    }
    publisher = JOBS["github-personal"].publisher
    assert publisher is not None
    with patch(
        f"{PREFIX}.qa_dataset_job.publish",
        new=AsyncMock(return_value={"url": "https://huggingface.co/datasets/ns/qa"}),
    ) as publish:
        result = await publisher(data, ["n2"], ["h1"])

    published = publish.call_args.args[0]
    assert [p.id for p in published.dataset.pairs] == ["k1", "n1", "h1"]
    assert published.dataset.review == []
    assert result.url == "https://huggingface.co/datasets/ns/qa"
    assert result.dry_run is False and dict(result.metrics)["New"] == 2


# --- knowledge-corpus -----------------------------------------------------------


async def test_corpus_requires_github_username(monkeypatch):
    monkeypatch.delenv("GITHUB_USERNAME", raising=False)
    with pytest.raises(CorpusJobError, match="GITHUB_USERNAME"):
        await JOBS["knowledge-corpus"].runner(KnowledgeCorpusOptions(), None, noop)


async def test_corpus_dry_run_skips_push(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("HF_DATASET_REPO", "ns/corpus")
    manifest = {
        "files": [{"source": "profile", "path": "data/profile.jsonl", "records": 4}]
    }
    with (
        patch(
            f"{PREFIX}.corpus_job.export_corpus", new=AsyncMock(return_value=manifest)
        ) as export,
        patch(f"{PREFIX}.corpus_job.push_corpus") as push,
    ):
        outcome = await JOBS["knowledge-corpus"].runner(
            KnowledgeCorpusOptions(sources=["profile"]), None, noop
        )

    assert export.call_args.args[1] == ["profile"]
    push.assert_not_called()
    assert outcome.draft is None
    assert (outcome.result.dry_run, outcome.result.metrics) == (True, [("profile", 4)])


async def test_corpus_pushes_when_not_dry_run(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("HF_DATASET_REPO", "ns/corpus")
    with (
        patch(
            f"{PREFIX}.corpus_job.export_corpus",
            new=AsyncMock(return_value={"files": []}),
        ),
        patch(
            f"{PREFIX}.corpus_job.push_corpus",
            return_value="https://huggingface.co/datasets/ns/corpus",
        ) as push,
    ):
        outcome = await JOBS["knowledge-corpus"].runner(
            KnowledgeCorpusOptions(dry_run=False), None, noop
        )
    push.assert_called_once()
    assert outcome.result.url == "https://huggingface.co/datasets/ns/corpus"


async def test_corpus_requires_hf_repo_to_push(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.delenv("HF_DATASET_REPO", raising=False)
    with (
        patch(
            f"{PREFIX}.corpus_job.export_corpus",
            new=AsyncMock(return_value={"files": []}),
        ),
        patch(f"{PREFIX}.corpus_job.push_corpus") as push,
    ):
        with pytest.raises(CorpusJobError, match="HF_DATASET_REPO"):
            await JOBS["knowledge-corpus"].runner(
                KnowledgeCorpusOptions(dry_run=False), None, noop
            )
    push.assert_not_called()


# --- background runs (Postgres) ------------------------------------------------


@pytest.fixture
def db(monkeypatch, test_engine):
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(jobs_service, "get_scoped_db", scoped)
    monkeypatch.setattr(jobs_service, "_TASKS", {})
    monkeypatch.setattr(jobs_service, "_PROGRESS", {})


def _patch_runner(monkeypatch, job_id, runner):
    spec = JOBS[job_id]
    monkeypatch.setitem(JOBS, job_id, type(spec)(**{**spec.__dict__, "runner": runner}))


async def _wait(run_id):
    task = jobs_service._TASKS.get(run_id)
    if task is not None:
        await task
    return get_run(run_id)


async def test_unknown_job_and_bad_options(db):
    with pytest.raises(UnknownJobError):
        await start_run("nope", {})
    with pytest.raises(ValidationError):
        await start_run("github-personal", {"max_repos": 0})
    with pytest.raises(UnknownRunError):
        get_run("missing")


async def test_draft_run_lifecycle(db, monkeypatch):
    release = asyncio.Event()

    async def runner(options, model_ref, progress):
        progress(1, 3, "repo-a")
        await release.wait()
        draft = _draft()
        return JobOutcome(
            JobResult(dry_run=True, metrics=[("New", 2)]),
            {
                "dataset": draft.dataset.to_dict(),
                "username": "kevin",
                "repo_id": "ns/qa",
            },
        )

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run("github-personal", {"max_repos": 1}, "openai:gpt-x")
    assert run["status"] == "running" and run["model_ref"] == "openai:gpt-x"
    await asyncio.sleep(0)
    assert get_run(run["id"])["progress"] == {"done": 1, "total": 3, "label": "repo-a"}

    # One run per job at a time.
    with pytest.raises(RunConflictError):
        await start_run("github-personal", {})

    release.set()
    done = await _wait(run["id"])
    assert done["status"] == "succeeded" and done["progress"] is None
    assert [p["id"] for p in done["preview"]["new"]] == ["n1", "n2"]
    assert done["published_url"] is None
    assert list_jobs()[0]["latest_run"] == {"id": run["id"], "status": "succeeded"}

    with patch(
        f"{PREFIX}.qa_dataset_job.publish",
        new=AsyncMock(return_value={"url": "https://huggingface.co/datasets/ns/qa"}),
    ):
        published = await publish_run(run["id"], exclude=["n1"])
    assert published["status"] == "published"
    assert published["published_url"] == "https://huggingface.co/datasets/ns/qa"

    with pytest.raises(RunConflictError):
        await publish_run(run["id"])  # already published


async def test_failed_run_records_the_error(db, monkeypatch):
    async def runner(options, model_ref, progress):
        raise qa_dataset.JobError("HF_TOKEN is required")

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run("github-personal", {})
    done = await _wait(run["id"])
    assert done["status"] == "failed" and done["error"] == "HF_TOKEN is required"
    with pytest.raises(RunConflictError):
        await publish_run(run["id"])


async def test_direct_run_records_its_url(db, monkeypatch):
    async def runner(options, model_ref, progress):
        return JobOutcome(JobResult(dry_run=False, url="https://hf.co/datasets/c"))

    _patch_runner(monkeypatch, "knowledge-corpus", runner)
    run = await start_run("knowledge-corpus", {"dry_run": False})
    done = await _wait(run["id"])
    assert done["status"] == "succeeded" and done["has_draft"] is False
    assert done["published_url"] == "https://hf.co/datasets/c"


async def test_run_lost_on_restart_is_interrupted(db, monkeypatch):
    never = asyncio.Event()

    async def runner(options, model_ref, progress):
        await never.wait()

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run("github-personal", {})
    task = jobs_service._TASKS.pop(run["id"])  # what a restart does
    task.cancel()
    assert get_run(run["id"])["status"] == "interrupted"
    # An interrupted run doesn't block a new one.
    _patch_runner(
        monkeypatch,
        "github-personal",
        AsyncMock(return_value=JobOutcome(JobResult(dry_run=True))),
    )
    assert (await start_run("github-personal", {}))["status"] == "running"
