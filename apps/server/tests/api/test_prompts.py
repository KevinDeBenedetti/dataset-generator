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


def test_list_prompts_shows_the_role_defaults(client: TestClient):
    """Each prompt names the model its role currently defaults to."""
    from unittest.mock import patch

    defaults = {
        "qa": "claude:q",
        "cleaning": "openai:c",
        "vision": "openai:v",
        "jobs": "x",
    }
    with patch("server.api.prompts.get_model_defaults", return_value=defaults):
        prompts = {p["key"]: p for p in client.get("/prompts").json()["prompts"]}
    assert prompts["qa_agent"]["model"] == "claude:q"
    assert prompts["cleaning"]["model"] == "openai:c"
    assert prompts["extraction"]["model"] == "openai:v"
    assert all(p["active"] for p in prompts.values())
