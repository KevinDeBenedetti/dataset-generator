"""Quality checks of a draft (services/draft_quality.py)."""

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.models.job_run import JobRun
from server.services import draft_quality, jobs as jobs_service
from server.services.jobs import RunConflictError, UnknownRunError
from server.services.users import create_user


@pytest.fixture
def owner(test_db):
    return create_user(test_db, email="owner@test.local", password="pw12345")


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
    monkeypatch.setattr(draft_quality, "get_scoped_db", scoped)
    monkeypatch.setattr(
        draft_quality,
        "get_quality_rules",
        lambda user_id: {"min_answer_words": 3, "reject_below_confidence": 0.5},
    )
    return scoped


def _pair(id_, question, answer, confidence=0.9):
    return {"id": id_, "question": question, "answer": answer, "confidence": confidence}


def _add(test_db, owner, run_id, job_id, draft):
    test_db.add(
        JobRun(
            id=run_id,
            owner_id=owner.id,
            job_id=job_id,
            status="succeeded",
            options={},
            draft=draft,
        )
    )
    test_db.commit()


def test_a_generation_draft_is_checked(db, owner, test_db):
    _add(
        test_db,
        owner,
        "g1",
        "generation-draft",
        {
            "pairs": [
                _pair(
                    "a",
                    "What is the install command?",
                    "Run make install to set it up.",
                ),
                _pair(
                    "b",
                    "What is the install command ?",
                    "Run make install to set it up!",
                ),
                _pair("c", "Who wrote it?", "Kevin.", confidence=0.95),
                _pair(
                    "d", "Is it fast?", "Yes, it is very fast indeed.", confidence=0.2
                ),
            ]
        },
    )

    checks = draft_quality.check_draft(owner.id, "g1", 0.85)

    assert [(d["first"], d["second"]) for d in checks["duplicates"]] == [("a", "b")]
    assert checks["flagged"] == {
        "c": "answer shorter than 3 words",
        "d": "confidence 0.20 below 0.50",
    }
    assert (checks["checked"], checks["total"]) == (4, 4)


def test_a_recipe_draft_checks_new_and_held_out_pairs_only(db, owner, test_db):
    kept = _pair("k", "Old question?", "An old answer, carried over.")
    new = _pair("n", "New question?", "A new answer for it.")
    held = _pair("h", "Held question?", "Short.")
    _add(
        test_db,
        owner,
        "r1",
        "github-recipe",
        {"dataset": {"pairs": [kept, new], "new_ids": ["n"], "review": [held]}},
    )

    checks = draft_quality.check_draft(owner.id, "r1", 0.85)

    assert checks["total"] == 2
    assert checks["flagged"] == {"h": "answer shorter than 3 words"}


def test_a_run_without_draft_or_of_someone_else(db, owner, test_db):
    _add(test_db, owner, "x1", "knowledge-corpus", None)
    with pytest.raises(RunConflictError):
        draft_quality.check_draft(owner.id, "x1", 0.85)
    with pytest.raises(UnknownRunError):
        draft_quality.check_draft("someone-else", "x1", 0.85)
