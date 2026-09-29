from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.services import scoring
from server.services.scoring import (
    ScoringNotConfiguredError,
    _format_batch,
    parse_scores,
    score_dataset,
)


def test_parse_scores_tolerates_prose_and_clamps():
    raw = (
        "Reasoning first… then the answer:\n"
        '{"scores": [{"i": 1, "confidence": 0.8}, {"i": 2, "confidence": 1.4}, '
        '{"i": 3, "confidence": -0.2}, {"i": 9, "confidence": 0.5}, '
        '{"i": 4, "confidence": "high"}]}'
    )
    assert parse_scores(raw, 4) == {1: 0.8, 2: 1.0, 3: 0.0}
    assert parse_scores("no json here", 3) == {}


def test_format_batch_includes_context_only_when_present():
    text = _format_batch(
        [
            {"question": "Q1?", "answer": "A1.", "context": "the source"},
            {"question": "Q2?", "answer": "A2.", "context": ""},
        ]
    )
    assert "[1]\nQ: Q1?\nA: A1.\nContext: the source" in text
    assert "[2]\nQ: Q2?\nA: A2." in text
    assert text.count("Context:") == 1


def _pairs(n):
    return [
        {"id": f"p{i}", "question": f"Q{i}?", "answer": f"A{i}.", "context": ""}
        for i in range(n)
    ]


def _chat_model(replies):
    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=[SimpleNamespace(content=r) for r in replies])
    return model


async def test_score_dataset_batches_and_stores_scores(monkeypatch):
    monkeypatch.setattr(scoring.config, "openai_api_key", "k")
    monkeypatch.setattr(scoring, "BATCH_SIZE", 2)
    chat = _chat_model(
        [
            '{"scores":[{"i":1,"confidence":0.9},{"i":2,"confidence":0.7}]}',
            '{"scores":[{"i":1,"confidence":0.4}]}',
        ]
    )
    stored = {}

    def fake_set(name, scores, method):
        stored.update(scores=scores, method=method)
        return len(scores)

    with (
        patch.object(scoring, "get_pairs_to_score", return_value=_pairs(3)),
        patch.object(scoring, "set_pair_confidences", side_effect=fake_set),
        patch.object(scoring, "build_chat_model", return_value=chat),
    ):
        result = await score_dataset("ds", model="judge")

    assert stored["scores"] == {"p0": 0.9, "p1": 0.7, "p2": 0.4}
    assert stored["method"] == "llm_judge:judge"
    assert result == {
        "dataset_name": "ds",
        "model": "judge",
        "requested": 3,
        "scored": 3,
        "failed": 0,
    }


async def test_score_dataset_counts_a_failed_batch(monkeypatch):
    monkeypatch.setattr(scoring.config, "openai_api_key", "k")
    chat = MagicMock()
    chat.ainvoke = AsyncMock(side_effect=RuntimeError("provider down"))

    with (
        patch.object(scoring, "get_pairs_to_score", return_value=_pairs(2)),
        patch.object(scoring, "set_pair_confidences", return_value=0) as set_scores,
        patch.object(scoring, "build_chat_model", return_value=chat),
    ):
        result = await score_dataset("ds", model="judge")

    assert set_scores.call_args.args[1] == {}
    assert (result["scored"], result["failed"]) == (0, 2)


async def test_score_dataset_requires_an_llm(monkeypatch):
    monkeypatch.setattr(scoring.config, "openai_api_key", "")
    with pytest.raises(ScoringNotConfiguredError):
        await score_dataset("ds")
