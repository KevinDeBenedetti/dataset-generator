"""Measuring the embedding checks' thresholds per model, and the user's choice
(services/calibration.py, services/semantic.py ``embedding_choice``)."""

from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from server.core.config import config
from server.models.user import User
from server.services import calibration, semantic
from server.services.calibration import best_threshold, measure
from server.services.semantic import EndpointEmbedder, Thresholds, embedding_choice
from server.tests.creds import FULL, replace
from server.tests.fake_embedder import FakeEmbedder

USER = "user-1"


def test_the_line_is_put_in_the_middle_of_the_gap():
    assert best_threshold([0.9, 0.8], [0.3, 0.5]) == (0.65, 1.0)


def test_with_an_overlap_the_line_separates_best():
    threshold, accuracy = best_threshold([0.9, 0.6, 0.7], [0.3, 0.65, 0.2])
    assert 0.6 < threshold <= 0.7 and accuracy == pytest.approx(0.833, abs=1e-3)


def test_a_line_stays_within_bounds():
    assert best_threshold([1.0, 1.0], [1.0])[0] == 0.99


def test_the_built_in_set_is_measured_with_the_model():
    report = measure(FakeEmbedder())
    for check in ("dedup", "grounding", "uncovered"):
        result = report[check]
        assert 0.05 <= result["threshold"] <= 0.99
        assert 0.5 <= result["accuracy"] <= 1.0
        assert result["positives"]["min"] <= result["positives"]["max"]
    assert report["dedup"]["examples"] == 32
    assert report["grounding"]["examples"] == 24
    assert report["model"] == FakeEmbedder.model_name


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

    monkeypatch.setattr(calibration, "get_scoped_db", scoped)
    with scoped() as session:
        session.add(User(id=USER, email="u1@test.local", role="user"))
        session.commit()


REPORT = {
    "model": "openai:embed-large",
    "dedup": {"threshold": 0.72},
    "grounding": {"threshold": 0.21},
    "uncovered": {"threshold": 0.3},
}


def test_the_chosen_model_and_its_thresholds_are_used(db, monkeypatch):
    monkeypatch.setattr(config, "openai_embedding_model", "embed-default")
    creds = replace(FULL, user_id=USER)
    # Nothing chosen: the server's model, with the defaults.
    first = embedding_choice(creds)
    assert (first.model_id, first.measured) == ("embed-default", False)

    calibration.save_choice(USER, "openai:embed-large", REPORT)
    chosen = embedding_choice(creds)
    assert chosen.model_id == "embed-large" and chosen.measured
    assert chosen.thresholds == Thresholds(0.72, 0.21, 0.3)
    report = calibration.calibration_report(USER, "openai:embed-large")
    assert report is not None and report["dedup"] == {"threshold": 0.72}

    # Back to the server's model: its own (unmeasured) defaults again.
    calibration.reset_choice(USER)
    back = embedding_choice(creds)
    assert (back.model_id, back.measured) == ("embed-default", False)
    # Another user, or none: the server's.
    assert embedding_choice(FULL).model_id == "embed-default"


def test_a_database_failure_leaves_the_defaults(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("no db")
        yield  # pragma: no cover

    monkeypatch.setattr(calibration, "get_scoped_db", broken)
    monkeypatch.setattr(config, "openai_embedding_model", "embed-default")
    choice = embedding_choice(replace(FULL, user_id=USER))
    assert choice.model_id == "embed-default" and not choice.measured


def test_an_embedder_carries_its_thresholds_to_the_checks():
    measured = Thresholds(0.7, 0.2, 0.3)
    embedder = EndpointEmbedder("embed-large", FULL, measured)
    assert semantic.thresholds_of(embedder) == measured
    assert semantic.thresholds_of(FakeEmbedder()) == semantic.default_thresholds()
