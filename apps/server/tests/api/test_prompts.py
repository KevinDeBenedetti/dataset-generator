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
    assert keys == {"qa_agent", "cleaning", "extraction"}

    for prompt in data["prompts"]:
        assert prompt["content"].strip() != ""
        assert prompt["role"] in {"system", "user", "assistant"}


def test_every_prompt_runs_on_your_llm(client: TestClient):
    """Each prompt names the model it runs on: your LLM, for every step."""
    from unittest.mock import patch

    with patch("server.api.prompts.get_default_model", return_value="openai:m"):
        prompts = {p["key"]: p for p in client.get("/prompts").json()["prompts"]}
    assert set(prompts) >= {"qa_agent", "cleaning", "extraction"}
    assert {p["model"] for p in prompts.values()} == {"openai:m"}
    assert all(p["active"] for p in prompts.values())
