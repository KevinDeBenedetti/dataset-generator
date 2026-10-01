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
from server.core.config import config
from server.services import jobs as jobs_service
from server.services import queue
from server.tests.creds import FULL, NONE, make_creds
from server.services.jobs import (
    RunConflictError,
    UnknownJobError,
    UnknownRunError,
    cancel_run,
    get_run,
    list_jobs,
    publish_run,
    start_run,
)

PREFIX = "server.jobs.registry"
OWNER = "owner-1"
OTHER = "owner-2"  # a second user, who must never see OWNER's runs
JOB_ENV = ("GITHUB_USERNAME", "HF_TOKEN", "HF_QA_DATASET_REPO", "HF_DATASET_REPO")


def noop(done, total, label):
    pass


@pytest.fixture(autouse=True)
def jobs_model(monkeypatch):
    """The jobs role default, without a DB."""
    monkeypatch.setattr(
        "server.services.jobs.resolve_model",
        lambda role, override=None, user_id=None: override or "claude:claude-sonnet-5",
    )
    monkeypatch.setattr("server.services.jobs.validate_ref", lambda ref, creds: ref)


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


def test_list_jobs_reports_what_to_add_in_settings():
    jobs = list_jobs(OWNER, NONE)
    assert {j["id"] for j in jobs} == {"github-personal", "knowledge-corpus"}
    personal = _job(jobs, "github-personal")
    assert personal["configured"] is False
    # The default model's provider credentials count too.
    assert personal["missing"] == [
        "your GitHub username",
        "your Hugging Face token",
        "the Q&A dataset repo",
        "your Claude token (`claude setup-token`) or Anthropic API key",
    ]
    assert personal["uses_model"] and personal["has_draft"]
    corpus = _job(jobs, "knowledge-corpus")
    assert corpus["uses_model"] is False and corpus["has_draft"] is False
    assert corpus["missing"] == [
        "your GitHub username",
        "your Hugging Face token",
        "the corpus dataset repo",
    ]


def test_configuration_is_judged_per_user():
    """One user's settings never make a job look configured for another."""
    ready = list_jobs(OWNER, FULL)
    assert all(j["configured"] for j in ready)
    assert not any(j["configured"] for j in list_jobs(OTHER, NONE))


def test_list_jobs_serves_option_schemas():
    jobs = list_jobs(OWNER, FULL)
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
            FULL,
            GitHubPersonalOptions(max_repos=2),
            "openai:gpt-x",
            lambda *a: progress.append(a),
        )

    kwargs = generate.call_args.kwargs
    assert generate.call_args.args[0] is FULL
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
        result = await publisher(FULL, data, ["n2"], ["h1"])

    assert publish.call_args.args[0] is FULL
    published = publish.call_args.args[1]
    assert [p.id for p in published.dataset.pairs] == ["k1", "n1", "h1"]
    assert published.dataset.review == []
    assert result.url == "https://huggingface.co/datasets/ns/qa"
    assert result.dry_run is False and dict(result.metrics)["New"] == 2


# --- knowledge-corpus -----------------------------------------------------------


async def test_corpus_requires_github_username():
    with pytest.raises(CorpusJobError, match="GitHub username"):
        await JOBS["knowledge-corpus"].runner(
            NONE, KnowledgeCorpusOptions(), None, noop
        )


async def test_corpus_dry_run_skips_push():
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
            FULL, KnowledgeCorpusOptions(sources=["profile"]), None, noop
        )

    assert export.call_args.args[1] == ["profile"]
    push.assert_not_called()
    assert outcome.draft is None
    assert (outcome.result.dry_run, outcome.result.metrics) == (True, [("profile", 4)])


async def test_corpus_pushes_when_not_dry_run():
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
            FULL, KnowledgeCorpusOptions(dry_run=False), None, noop
        )
    push.assert_called_once()
    assert outcome.result.url == "https://huggingface.co/datasets/ns/corpus"


async def test_corpus_requires_hf_repo_to_push():
    creds = make_creds(github_username="kevin", hf_token="hf_x")
    with (
        patch(
            f"{PREFIX}.corpus_job.export_corpus",
            new=AsyncMock(return_value={"files": []}),
        ),
        patch(f"{PREFIX}.corpus_job.push_corpus") as push,
    ):
        with pytest.raises(CorpusJobError, match="corpus dataset repo"):
            await JOBS["knowledge-corpus"].runner(
                creds, KnowledgeCorpusOptions(dry_run=False), None, noop
            )
    push.assert_not_called()


# --- queued runs and the worker ---------------------------------------------


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
    monkeypatch.setattr(queue, "get_scoped_db", scoped)
    # Fast heart-beats so progress and cancellation show up quickly.
    monkeypatch.setattr(config, "worker_heartbeat_seconds", 0.02)
    monkeypatch.setattr(config, "worker_poll_seconds", 0.01)
    monkeypatch.setattr(config, "quota_active_runs", 0)
    monkeypatch.setattr(config, "quota_runs_per_day", 0)
    # The worker resolves the owner's credentials itself; record whose.
    resolved = []

    def resolve(owner_id):
        resolved.append(owner_id)
        return FULL

    monkeypatch.setattr("server.services.credentials.resolve_credentials", resolve)

    from server.models.user import User

    with scoped() as session:
        session.add(User(id=OWNER, email="owner1@test.local", role="user"))
        session.add(User(id=OTHER, email="owner2@test.local", role="user"))
        session.commit()
    return resolved


def _patch_runner(monkeypatch, job_id, runner):
    spec = JOBS[job_id]
    monkeypatch.setitem(JOBS, job_id, type(spec)(**{**spec.__dict__, "runner": runner}))


async def _wait(run_id, owner=OWNER):
    """Let a worker take queued runs until ``run_id`` is done."""
    while get_run(owner, run_id)["status"] in ("queued", "running"):
        if await queue.run_once() is None:
            await asyncio.sleep(0.01)
    return get_run(owner, run_id)


async def _until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        assert loop.time() < end, "condition not reached"
        await asyncio.sleep(0.01)


async def test_unknown_job_and_bad_options(db):
    with pytest.raises(UnknownJobError):
        await start_run(OWNER, FULL, "nope", {})
    with pytest.raises(ValidationError):
        await start_run(OWNER, FULL, "github-personal", {"max_repos": 0})
    with pytest.raises(UnknownRunError):
        get_run(OWNER, "missing")


async def test_the_api_only_queues_a_worker_runs_it(db, monkeypatch):
    release = asyncio.Event()

    async def runner(creds, options, model_ref, progress):
        assert creds is FULL
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
    run = await start_run(
        OWNER, FULL, "github-personal", {"max_repos": 1}, "openai:gpt-x"
    )
    assert run["status"] == "queued" and run["model_ref"] == "openai:gpt-x"
    # Nothing runs until a worker claims it.
    await asyncio.sleep(0.05)
    assert get_run(OWNER, run["id"])["status"] == "queued"
    # One run per job at a time — queued counts.
    with pytest.raises(RunConflictError):
        await start_run(OWNER, FULL, "github-personal", {})

    worker = asyncio.create_task(queue.run_once("w1"))
    await _until(
        lambda: (get_run(OWNER, run["id"])["progress"] or {}).get("label") == "repo-a"
    )
    live = get_run(OWNER, run["id"])
    assert live["status"] == "running"
    assert live["progress"] == {"done": 1, "total": 3, "label": "repo-a"}
    release.set()
    await worker

    done = get_run(OWNER, run["id"])
    assert done["status"] == "succeeded" and done["progress"] is None
    assert [p["id"] for p in done["preview"]["new"]] == ["n1", "n2"]
    assert db == [OWNER]  # the owner's credentials, resolved by the worker
    assert list_jobs(OWNER, FULL)[0]["latest_run"] == {
        "id": run["id"],
        "status": "succeeded",
    }

    with patch(
        f"{PREFIX}.qa_dataset_job.publish",
        new=AsyncMock(return_value={"url": "https://huggingface.co/datasets/ns/qa"}),
    ):
        published = await publish_run(OWNER, FULL, run["id"], exclude=["n1"])
    assert published["status"] == "published"
    with pytest.raises(RunConflictError):
        await publish_run(OWNER, FULL, run["id"])  # already published


async def test_two_publishes_of_one_draft_only_publish_once(db, monkeypatch):
    run = await _finished_draft_run(monkeypatch, OWNER)
    gate = asyncio.Event()

    async def slow_publish(creds, draft):
        await gate.wait()
        return {"url": "https://huggingface.co/datasets/ns/qa"}

    with patch(f"{PREFIX}.qa_dataset_job.publish", new=slow_publish):
        first = asyncio.create_task(publish_run(OWNER, FULL, run["id"]))
        await _until(lambda: get_run(OWNER, run["id"])["status"] == "publishing")
        with pytest.raises(RunConflictError):
            await publish_run(OWNER, FULL, run["id"])
        gate.set()
        assert (await first)["status"] == "published"


async def test_a_failed_publish_can_be_retried(db, monkeypatch):
    run = await _finished_draft_run(monkeypatch, OWNER)
    with patch(
        f"{PREFIX}.qa_dataset_job.publish",
        new=AsyncMock(side_effect=RuntimeError("hub down")),
    ):
        with pytest.raises(RuntimeError):
            await publish_run(OWNER, FULL, run["id"])
    assert get_run(OWNER, run["id"])["status"] == "succeeded"


async def test_failed_run_records_the_error(db, monkeypatch):
    async def runner(creds, options, model_ref, progress):
        raise qa_dataset.JobError("HF_TOKEN is required")

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run(OWNER, FULL, "github-personal", {})
    done = await _wait(run["id"])
    assert done["status"] == "failed" and done["error"] == "HF_TOKEN is required"
    with pytest.raises(RunConflictError):
        await publish_run(OWNER, FULL, run["id"])


async def test_direct_run_records_its_url(db, monkeypatch):
    async def runner(creds, options, model_ref, progress):
        return JobOutcome(JobResult(dry_run=False, url="https://hf.co/datasets/c"))

    _patch_runner(monkeypatch, "knowledge-corpus", runner)
    run = await start_run(OWNER, FULL, "knowledge-corpus", {"dry_run": False})
    done = await _wait(run["id"])
    assert done["status"] == "succeeded" and done["has_draft"] is False
    assert done["published_url"] == "https://hf.co/datasets/c"


async def test_a_queued_run_is_cancelled_at_once(db, monkeypatch):
    _patch_runner(
        monkeypatch, "github-personal", AsyncMock(side_effect=AssertionError("ran"))
    )
    run = await start_run(OWNER, FULL, "github-personal", {})

    assert cancel_run(OWNER, run["id"])["status"] == "cancelled"
    assert await queue.run_once() is None  # nothing left to claim
    with pytest.raises(RunConflictError):
        cancel_run(OWNER, run["id"])


async def test_a_running_run_is_stopped_by_its_worker(db, monkeypatch):
    stopped = asyncio.Event()

    async def runner(creds, options, model_ref, progress):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run(OWNER, FULL, "github-personal", {})
    worker = asyncio.create_task(queue.run_once())
    await _until(lambda: get_run(OWNER, run["id"])["status"] == "running")

    assert cancel_run(OWNER, run["id"])["cancel_requested"] is True
    await asyncio.wait_for(worker, 2)
    assert stopped.is_set()
    assert get_run(OWNER, run["id"])["status"] == "cancelled"


def _row(job_id="github-personal", owner=OWNER, status="running", **fields):
    from server.models.job_run import JobRun

    with jobs_service.get_scoped_db() as db:
        row = JobRun(owner_id=owner, job_id=job_id, status=status, options={}, **fields)
        db.add(row)
        db.commit()
        return row.id


def test_a_run_whose_worker_died_is_interrupted_not_rerun(db):
    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    dead = _row(heartbeat_at=old, claimed_by="gone")
    alive = _row(
        "knowledge-corpus", heartbeat_at=datetime.now(timezone.utc), claimed_by="w"
    )

    assert queue.reap_stale(stale_after=120) == 1
    interrupted = get_run(OWNER, dead)
    assert interrupted["status"] == "interrupted" and "stopped" in interrupted["error"]
    assert get_run(OWNER, alive)["status"] == "running"
    assert queue.claim_next("w2") is None  # interrupted is never claimed again


async def test_an_interrupted_run_frees_the_slot(db, monkeypatch):
    _row(status="interrupted")
    _patch_runner(
        monkeypatch,
        "github-personal",
        AsyncMock(return_value=JobOutcome(JobResult(dry_run=True))),
    )
    assert (await start_run(OWNER, FULL, "github-personal", {}))["status"] == "queued"


def test_two_workers_never_claim_the_same_run(db):
    first = _row(status="queued")
    second = _row("knowledge-corpus", status="queued")

    claims = [queue.claim_next("w1"), queue.claim_next("w2"), queue.claim_next("w3")]

    assert sorted(c for c in claims if c) == sorted([first, second])
    assert claims[2] is None
    assert get_run(OWNER, first)["status"] == "running"


async def test_a_worker_only_finishes_runs_it_still_owns(db, monkeypatch):
    """Reaped while it hung: the late result must not resurrect the run."""
    release = asyncio.Event()

    async def runner(creds, options, model_ref, progress):
        await release.wait()
        return JobOutcome(JobResult(dry_run=True))

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run(OWNER, FULL, "github-personal", {})
    worker = asyncio.create_task(queue.run_once("slow"))
    await _until(lambda: get_run(OWNER, run["id"])["status"] == "running")
    with jobs_service.get_scoped_db() as session:
        from server.models.job_run import JobRun

        session.get(JobRun, run["id"]).status = "interrupted"
        session.commit()
    release.set()
    await asyncio.wait_for(worker, 2)
    assert get_run(OWNER, run["id"])["status"] == "interrupted"


async def test_stopping_a_worker_drains_its_current_run(db, monkeypatch):
    release = asyncio.Event()

    async def runner(creds, options, model_ref, progress):
        await release.wait()
        return JobOutcome(JobResult(dry_run=True))

    _patch_runner(monkeypatch, "github-personal", runner)
    monkeypatch.setattr(config, "worker_drain_seconds", 2)
    run = await start_run(OWNER, FULL, "github-personal", {})
    stop = asyncio.Event()
    loop = asyncio.create_task(queue.run_forever(stop))
    await _until(lambda: get_run(OWNER, run["id"])["status"] == "running")

    stop.set()  # SIGTERM
    await asyncio.sleep(0.05)
    assert not loop.done()  # still draining
    release.set()
    await asyncio.wait_for(loop, 2)
    assert get_run(OWNER, run["id"])["status"] == "succeeded"


async def test_quotas_on_active_and_daily_runs(db, monkeypatch):
    from server.services.jobs import QuotaExceededError

    _patch_runner(
        monkeypatch,
        "github-personal",
        AsyncMock(return_value=JobOutcome(JobResult(dry_run=True))),
    )
    _patch_runner(
        monkeypatch,
        "knowledge-corpus",
        AsyncMock(return_value=JobOutcome(JobResult(dry_run=True))),
    )
    monkeypatch.setattr(config, "quota_active_runs", 1)
    await start_run(OWNER, FULL, "github-personal", {})
    with pytest.raises(QuotaExceededError, match="in progress"):
        await start_run(OWNER, FULL, "knowledge-corpus", {})
    # Someone else's runs don't count against you.
    await start_run(OTHER, FULL, "knowledge-corpus", {})

    monkeypatch.setattr(config, "quota_active_runs", 0)
    monkeypatch.setattr(config, "quota_runs_per_day", 2)
    corpus = await start_run(OWNER, FULL, "knowledge-corpus", {})
    await _wait(corpus["id"])  # finished, but still counts for the day
    with pytest.raises(QuotaExceededError, match="Daily limit"):
        await start_run(OWNER, FULL, "knowledge-corpus", {})


def test_the_database_refuses_a_second_active_run(db):
    from sqlalchemy.exc import IntegrityError

    _row("github-personal")
    with pytest.raises(IntegrityError):
        _row("github-personal", status="queued")  # queued counts as active
    _row("knowledge-corpus", status="queued")
    _row("github-personal", status="succeeded")


async def test_losing_the_insert_race_is_a_conflict_not_a_crash(db, monkeypatch):
    """Two requests pass the in-memory check together: the unique index lets one
    insert win and the loser must surface as a clean conflict."""
    from server.models.job_run import JobRun

    _row("github-personal")  # the winner, from "another process"
    real_scope = jobs_service.get_scoped_db

    class RacySession:
        """Its first look for an active run comes back empty (the stale check)."""

        def __init__(self, real):
            self._real, self._blind = real, True

        def query(self, *entities):
            if self._blind and entities and entities[0] is JobRun:
                self._blind = False

                class Nothing:
                    def filter(self, *_):
                        return self

                    def first(self):
                        return None

                return Nothing()
            return self._real.query(*entities)

        def __getattr__(self, name):
            return getattr(self._real, name)

    @contextmanager
    def racy():
        with real_scope() as session:
            yield RacySession(session)

    monkeypatch.setattr(jobs_service, "get_scoped_db", racy)
    with pytest.raises(RunConflictError):
        await start_run(OWNER, FULL, "github-personal", {})


# --- isolation between users --------------------------------------------------


async def _finished_draft_run(monkeypatch, owner):
    async def runner(creds, options, model_ref, progress):
        draft = _draft()
        return JobOutcome(
            JobResult(dry_run=True),
            {
                "dataset": draft.dataset.to_dict(),
                "username": "kevin",
                "repo_id": "ns/qa",
            },
        )

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run(owner, FULL, "github-personal", {})
    await _wait(run["id"], owner)
    return run


async def test_a_run_of_another_user_looks_like_it_does_not_exist(db, monkeypatch):
    run = await _finished_draft_run(monkeypatch, OWNER)

    assert get_run(OWNER, run["id"])["status"] == "succeeded"
    for action in (
        lambda: get_run(OTHER, run["id"]),
        lambda: cancel_run(OTHER, run["id"]),
    ):
        with pytest.raises(UnknownRunError):
            action()
    with pytest.raises(UnknownRunError):
        await publish_run(OTHER, FULL, run["id"])


async def test_a_stranger_cannot_publish_your_draft(db, monkeypatch):
    run = await _finished_draft_run(monkeypatch, OWNER)

    with (
        patch(f"{PREFIX}.qa_dataset_job.publish", new=AsyncMock()) as publish,
        pytest.raises(UnknownRunError),
    ):
        await publish_run(OTHER, FULL, run["id"])
    publish.assert_not_called()
    assert get_run(OWNER, run["id"])["status"] == "succeeded"


async def test_the_latest_run_shown_in_the_catalogue_is_your_own(db, monkeypatch):
    mine = await _finished_draft_run(monkeypatch, OWNER)

    assert list_jobs(OWNER, FULL)[0]["latest_run"] == {
        "id": mine["id"],
        "status": "succeeded",
    }
    assert list_jobs(OTHER, FULL)[0]["latest_run"] is None


async def test_each_run_executes_with_its_owners_credentials(db, monkeypatch):
    _patch_runner(
        monkeypatch,
        "github-personal",
        AsyncMock(return_value=JobOutcome(JobResult(dry_run=True))),
    )
    mine = await start_run(OWNER, FULL, "github-personal", {})
    theirs = await start_run(OTHER, FULL, "github-personal", {})  # not the same user
    await _wait(mine["id"])
    await _wait(theirs["id"], OTHER)
    assert sorted(db) == sorted([OWNER, OTHER])


def test_the_database_allows_one_active_run_per_user_and_job_only(db):
    from sqlalchemy.exc import IntegrityError

    _row("github-personal", OWNER)
    _row("github-personal", OTHER)  # another owner: fine
    with pytest.raises(IntegrityError):
        _row("github-personal", OWNER)


async def test_a_key_echoed_in_an_error_is_not_stored_on_the_run(db, monkeypatch):
    leaked = "sk-canary-0123456789abcdefABCDEF"

    async def runner(creds, options, model_ref, progress):
        raise RuntimeError(f"401 Incorrect API key provided: {leaked}")

    _patch_runner(monkeypatch, "github-personal", runner)
    run = await start_run(OWNER, FULL, "github-personal", {})
    done = await _wait(run["id"])

    assert done["status"] == "failed"
    assert leaked not in done["error"]
    assert "Incorrect API key provided" in done["error"]
