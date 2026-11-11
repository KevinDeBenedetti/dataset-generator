"""Job schedules (services/schedules.py): the presets' arithmetic, saving
the settings, and the worker's sweep that queues the due runs."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from server.jobs.resume_qa import RESUME_JOB_ID
from server.models.job_run import JobRun
from server.models.job_schedule import JobSchedule
from server.models.user import User
from server.services import jobs as jobs_service
from server.services import queue, schedules
from server.services.schedules import (
    ScheduleInputError,
    ScheduleNotFoundError,
    next_run,
    queue_due,
    upsert_schedule,
)
from server.tests.creds import FULL

OWNER = "owner-1"
OTHER = "owner-2"
OPTIONS = {"resume_id": "r1", "target_repo": "kevin/resume-qa"}


def _utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def _as_utc(value):
    # The database hands naive timestamps back (UTC by construction).
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- when ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("every", "after", "expected"),
    [
        # Later today, else tomorrow.
        ("day", _utc(2026, 11, 10, 2, 0), _utc(2026, 11, 10, 3, 0)),
        ("day", _utc(2026, 11, 10, 3, 0), _utc(2026, 11, 11, 3, 0)),
        # 2026-11-10 is a Tuesday: the next Monday; on a Monday, later that day.
        ("week", _utc(2026, 11, 10, 2, 0), _utc(2026, 11, 16, 3, 0)),
        ("week", _utc(2026, 11, 16, 2, 0), _utc(2026, 11, 16, 3, 0)),
        ("week", _utc(2026, 11, 16, 3, 0), _utc(2026, 11, 23, 3, 0)),
        # The next 1st of a month, across the year too.
        ("month", _utc(2026, 11, 10, 2, 0), _utc(2026, 12, 1, 3, 0)),
        ("month", _utc(2026, 12, 1, 2, 0), _utc(2026, 12, 1, 3, 0)),
        ("month", _utc(2026, 12, 31, 23, 0), _utc(2027, 1, 1, 3, 0)),
    ],
)
def test_the_next_run_follows_the_calendar(every, after, expected):
    assert next_run(every, 3, 0, after) == expected


def test_a_naive_date_reads_as_utc():
    assert next_run("day", 3, 0, datetime(2026, 11, 10, 4, 0)) == _utc(
        2026, 11, 11, 3, 0
    )


def test_an_unknown_preset_is_refused():
    with pytest.raises(ScheduleInputError, match="Unknown preset"):
        next_run("hour", 3, 0, _utc(2026, 1, 1))


# --- saving ----------------------------------------------------------------------------


@pytest.fixture
def db(monkeypatch, test_engine):
    """One test database for the schedules, the jobs and the worker."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    for module in (jobs_service, queue, schedules):
        monkeypatch.setattr(module, "get_scoped_db", scoped)
    monkeypatch.setattr(
        "server.services.credentials.resolve_credentials", lambda owner_id: FULL
    )
    # Your LLM, without the model defaults table.
    monkeypatch.setattr(
        "server.services.jobs.resolve_model",
        lambda override=None, user_id=None: override or "openai:chat-default",
    )
    monkeypatch.setattr("server.services.jobs.validate_ref", lambda ref, creds: ref)
    session = TestingSession()
    session.add(User(id=OWNER, email="owner1@test.local", role="admin"))
    session.add(User(id=OTHER, email="owner2@test.local", role="user"))
    session.commit()
    yield session
    session.close()


def test_saving_checks_the_options_and_sets_the_first_run(db):
    before = datetime.now(timezone.utc)
    saved = upsert_schedule(
        db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="day", at_hour=4
    )

    assert saved["options"] == {
        "resume_id": "r1",
        "title": "",
        "target_repo": "kevin/resume-qa",
        "language": "auto",
        "full_refresh": False,
        "publish": False,
    }
    assert (saved["every"], saved["at_hour"], saved["at_minute"]) == ("day", 4, 0)
    assert saved["next_run_at"] > before and saved["next_run_at"].hour == 4
    assert saved["last_run"] is None
    assert schedules.get_schedule(db, OWNER, RESUME_JOB_ID, "r1")["id"] == saved["id"]

    with pytest.raises(ScheduleInputError, match="preset"):
        upsert_schedule(db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="hour")
    with pytest.raises(ScheduleInputError, match="hour"):
        upsert_schedule(db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, at_hour=24)
    with pytest.raises(ScheduleInputError, match="pattern"):
        upsert_schedule(
            db,
            OWNER,
            RESUME_JOB_ID,
            "r1",
            options={**OPTIONS, "target_repo": "no way"},
        )
    with pytest.raises(ScheduleInputError, match="Unknown job"):
        upsert_schedule(db, OWNER, "nope", "r1", options={})


def test_the_next_run_moves_only_with_the_timing(db):
    first = upsert_schedule(
        db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="week"
    )
    same = upsert_schedule(
        db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="week", publish=True
    )
    assert same["next_run_at"] == first["next_run_at"] and same["publish"] is True

    moved = upsert_schedule(
        db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="week", at_hour=5
    )
    assert moved["next_run_at"].hour == 5

    off = upsert_schedule(db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every=None)
    assert off["next_run_at"] is None and off["every"] is None
    assert db.query(JobSchedule).count() == 1  # one row per owner, job and scope


def test_schedules_belong_to_their_owner(db):
    upsert_schedule(db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS)
    with pytest.raises(ScheduleNotFoundError):
        schedules.get_schedule(db, OTHER, RESUME_JOB_ID, "r1")
    with pytest.raises(ScheduleNotFoundError):
        schedules.delete_schedule(db, OTHER, RESUME_JOB_ID, "r1")
    assert [s["scope"] for s in schedules.list_schedules(db, OWNER)] == ["r1"]
    assert schedules.list_schedules(db, OTHER) == []
    schedules.delete_schedule(db, OWNER, RESUME_JOB_ID, "r1")
    assert db.query(JobSchedule).count() == 0


# --- the sweep ---------------------------------------------------------------------------


def _due(db, owner=OWNER, scope="r1", **values):
    saved = upsert_schedule(
        db, owner, RESUME_JOB_ID, scope, options=OPTIONS, every="day", **values
    )
    row = db.get(JobSchedule, saved["id"])
    row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    return row


def test_the_sweep_queues_a_due_run_once(db):
    row = _due(db, publish=True)
    now = datetime.now(timezone.utc)

    queued = queue_due(now)

    assert len(queued) == 1
    run = db.get(JobRun, queued[0])
    assert (run.owner_id, run.job_id, run.status) == (OWNER, RESUME_JOB_ID, "queued")
    assert run.options["publish"] is True and run.options["resume_id"] == "r1"
    assert run.model_ref == "openai:chat-default"
    db.refresh(row)
    assert row.last_run_id == run.id
    assert _as_utc(row.next_run_at) > now
    assert schedules.get_schedule(db, OWNER, RESUME_JOB_ID, "r1")["last_run"] == {
        "id": run.id,
        "status": "queued",
    }
    # The tick is spent: the next sweep finds nothing.
    assert queue_due(now) == []


def test_the_sweep_skips_what_it_can_not_run_and_moves_on(db):
    busy = _due(db, scope="r1")
    other = _due(db, owner=OTHER, scope="r2")  # not an admin: never queued
    upsert_schedule(db, OWNER, RESUME_JOB_ID, "manual", options=OPTIONS, every=None)
    now = datetime.now(timezone.utc)

    assert len(queue_due(now)) == 1  # OWNER's; the manual one is never due

    # A run of the job still in progress: this tick is skipped, not queued twice.
    busy.next_run_at = now - timedelta(minutes=1)
    db.commit()
    assert queue_due(now) == []
    db.refresh(busy)
    assert _as_utc(busy.next_run_at) > now  # the date moved on anyway
    db.refresh(other)
    assert other.last_run_id is None
    assert _as_utc(other.next_run_at) > now
    assert db.query(JobRun).count() == 1


def test_a_schedule_whose_time_has_not_come_waits(db):
    upsert_schedule(db, OWNER, RESUME_JOB_ID, "r1", options=OPTIONS, every="day")
    assert queue_due(datetime.now(timezone.utc)) == []
    assert db.query(JobRun).count() == 0
