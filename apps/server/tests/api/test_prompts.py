"""
Tests for the /prompts API endpoint.

Unlike the other new endpoints, /prompts has no service layer to mock — it
assembles its response directly from the prompt constants shipped in
services/llm.py and services/agent.py, so these tests exercise it end to end.
"""

from fastapi.testclient import TestClient


def test_list_prompts(client: TestClient):
    """Test that /prompts returns every shipped prompt with the expected shape."""
    response = client.get("/prompts")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == len(data["prompts"])
    assert data["total"] > 0

    keys = {p["key"] for p in data["prompts"]}
    assert {"qa_agent", "cleaning", "extraction", "qa_legacy"} <= keys

    for prompt in data["prompts"]:
        assert prompt["content"].strip() != ""
        assert prompt["role"] in {"system", "user", "assistant"}


def test_list_prompts_marks_legacy_inactive(client: TestClient):
    """Test the superseded legacy QA prompt is flagged inactive; live ones aren't."""
    response = client.get("/prompts")
    prompts = {p["key"]: p for p in response.json()["prompts"]}

    assert prompts["qa_legacy"]["active"] is False
    assert prompts["qa_agent"]["active"] is True
