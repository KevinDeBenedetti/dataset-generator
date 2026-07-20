"""
Tests for the quality-rules API endpoints.

The `client` fixture already overrides `require_admin` with a test admin, so
these tests exercise the handler logic (mocking the persistence-layer
functions) rather than the admin gate itself — that's covered separately in
test_route_protection.py.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient


def _rules(**overrides):
    base = {
        "min_answer_words": 0,
        "reject_below_confidence": 0.0,
        "auto_reject_enabled": False,
        "updated_at": None,
    }
    base.update(overrides)
    return base


def test_get_quality_rules_defaults(client: TestClient):
    """Test reading the quality rules when none have been persisted yet."""
    with patch("server.api.quality_rules.get_quality_rules", return_value=_rules()):
        response = client.get("/quality-rules")
    assert response.status_code == 200
    data = response.json()
    assert data["min_answer_words"] == 0
    assert data["auto_reject_enabled"] is False


def test_update_quality_rules_success(client: TestClient):
    """Test a partial update of the quality rules."""
    updated = _rules(
        min_answer_words=5,
        reject_below_confidence=0.6,
        auto_reject_enabled=True,
        updated_at="2026-01-01T00:00:00",
    )
    with patch(
        "server.api.quality_rules.update_quality_rules", return_value=updated
    ) as mock_update:
        response = client.put(
            "/quality-rules",
            json={
                "min_answer_words": 5,
                "reject_below_confidence": 0.6,
                "auto_reject_enabled": True,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["min_answer_words"] == 5
    assert data["reject_below_confidence"] == 0.6
    assert data["auto_reject_enabled"] is True
    mock_update.assert_called_once_with(
        min_answer_words=5,
        reject_below_confidence=0.6,
        auto_reject_enabled=True,
    )


def test_update_quality_rules_partial(client: TestClient):
    """Test that omitted fields are forwarded as None (service keeps them unchanged)."""
    with patch(
        "server.api.quality_rules.update_quality_rules", return_value=_rules()
    ) as mock_update:
        response = client.put("/quality-rules", json={"min_answer_words": 3})
    assert response.status_code == 200
    mock_update.assert_called_once_with(
        min_answer_words=3,
        reject_below_confidence=None,
        auto_reject_enabled=None,
    )


def test_update_quality_rules_invalid_confidence(client: TestClient):
    """Test the update endpoint rejects an out-of-range confidence value."""
    response = client.put("/quality-rules", json={"reject_below_confidence": 1.5})
    assert response.status_code == 422


def test_update_quality_rules_service_error(client: TestClient):
    """Test that a service-layer failure surfaces as a 500."""
    with patch(
        "server.api.quality_rules.update_quality_rules",
        side_effect=RuntimeError("db unavailable"),
    ):
        response = client.put("/quality-rules", json={"min_answer_words": 1})
    assert response.status_code == 500
