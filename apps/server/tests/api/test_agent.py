"""The QA agent's verification route (Verify QA page): POST /agent/qa-test."""

import json
from unittest.mock import AsyncMock, patch

PAIR = {
    "question": "What does the dataset generator publish?",
    "answer": "Private question-answer datasets on Hugging Face.",
    "context": "The generator publishes private Q&A datasets to the Hub.",
    "confidence": 0.9,
}


def test_the_agent_runs_on_a_text_and_returns_raw_and_parsed_output(client):
    raw = json.dumps({"items": [PAIR]})
    with (
        patch("server.api.agent.validate_ref", return_value="openai:gpt-x"),
        patch(
            "server.services.agent.QAAgentService._run", new=AsyncMock(return_value=raw)
        ),
    ):
        response = client.post(
            "/agent/qa-test",
            json={"text": "Some source text.", "target_language": "en"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["count"] == 1
    assert body["raw_response"] == raw and body["raw_length"] == len(raw)
    assert body["qa_pairs"][0]["question"] == PAIR["question"]


def test_an_unusable_model_is_refused_before_the_agent_runs(client):
    with patch(
        "server.api.agent.validate_ref", side_effect=ValueError("Unknown model 'x'")
    ):
        response = client.post(
            "/agent/qa-test", json={"text": "Some text.", "model": "x"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown model 'x'"
