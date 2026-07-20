"""Tests for the persisted quality rules service."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from server.services.quality_rules import (
    DEFAULT_RULES,
    get_quality_rules,
    rejection_reason,
    update_quality_rules,
)


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, test_engine):
    """Point the service at the per-test in-memory engine, never datasets.db."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    @contextmanager
    def scoped():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("server.services.quality_rules.get_scoped_db", scoped)


def test_get_quality_rules_defaults_when_unset():
    # No row yet → the enforcement-off defaults.
    rules = get_quality_rules()
    assert rules["auto_reject_enabled"] is False
    assert rules["min_answer_words"] == DEFAULT_RULES["min_answer_words"]


def test_get_quality_rules_defaults_when_db_unreachable():
    with patch(
        "server.services.quality_rules.get_scoped_db",
        side_effect=RuntimeError("db down"),
    ):
        rules = get_quality_rules()
    assert rules == DEFAULT_RULES


def test_update_then_get_roundtrip():
    updated = update_quality_rules(
        min_answer_words=5, reject_below_confidence=0.6, auto_reject_enabled=True
    )
    assert updated["min_answer_words"] == 5
    assert updated["reject_below_confidence"] == 0.6
    assert updated["auto_reject_enabled"] is True

    fetched = get_quality_rules()
    assert fetched["min_answer_words"] == 5
    assert fetched["auto_reject_enabled"] is True

    # Partial update keeps the other fields.
    update_quality_rules(auto_reject_enabled=False)
    fetched = get_quality_rules()
    assert fetched["auto_reject_enabled"] is False
    assert fetched["min_answer_words"] == 5


def test_rejection_reason_disabled_is_noop():
    rules = {
        "auto_reject_enabled": False,
        "min_answer_words": 100,
        "reject_below_confidence": 1.0,
    }
    assert rejection_reason("short", 0.0, rules) is None
    assert rejection_reason("short", 0.0, {}) is None


def test_rejection_reason_enforces_min_words_and_confidence():
    rules = {
        "auto_reject_enabled": True,
        "min_answer_words": 3,
        "reject_below_confidence": 0.7,
    }
    assert rejection_reason("too short", 0.9, rules) is not None  # 2 words
    assert rejection_reason("this is long enough", 0.5, rules) is not None  # low conf
    assert rejection_reason("this is long enough", 0.9, rules) is None
