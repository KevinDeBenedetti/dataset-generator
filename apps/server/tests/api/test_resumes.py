"""The /resumes routes: admins only, errors answered with what to fix.

The service is mocked: tests/services/test_reactive_resume.py covers the
instance. The app here keeps the real ``require_admin``, so the role check is
the real one.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import resumes
from server.models.user import User, UserRole
from server.services import reactive_resume as rr
from server.services.auth import get_current_user

ADMIN = User(id="a1", email="admin@example.com", role=UserRole.ADMIN)
USER = User(id="u1", email="user@example.com", role=UserRole.USER)

LISTING = {
    "instance": "https://cv.example.org",
    "resumes": [
        {
            "id": "r1",
            "name": "Engineer",
            "slug": "engineer",
            "tags": [],
            "is_public": False,
            "is_locked": False,
            "updated_at": None,
        }
    ],
}


def _client(user: User) -> TestClient:
    app = FastAPI()
    app.include_router(resumes.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_an_admin_lists_the_resumes():
    with patch.object(rr, "list_resumes", AsyncMock(return_value=LISTING)):
        response = _client(ADMIN).get("/resumes")
    assert response.status_code == 200
    assert response.json() == LISTING


def test_anyone_else_is_turned_away_before_anything_is_read():
    with (
        patch.object(rr, "list_resumes", AsyncMock(return_value=LISTING)) as listing,
        patch.object(rr, "get_resume", AsyncMock()) as fetch,
    ):
        assert _client(USER).get("/resumes").status_code == 403
        assert _client(USER).get("/resumes/r1").status_code == 403
    listing.assert_not_called()
    fetch.assert_not_called()


def test_a_resume_is_served_as_text():
    view = rr.resume_view(
        {
            "id": "r1",
            "name": "Engineer",
            "slug": "engineer",
            "data": {
                "basics": {"name": "Kevin"},
                "summary": {"content": "<p>Hi</p>"},
                "sections": {
                    "skills": {"title": "Skills", "items": [{"id": "s", "name": "Go"}]}
                },
            },
        }
    )
    with patch.object(rr, "get_resume", AsyncMock(return_value=view)) as fetch:
        response = _client(ADMIN).get("/resumes/r1")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Hi" and body["sections"][0]["items"][0]["title"] == "Go"
    fetch.assert_awaited_once_with("r1")


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (rr.ResumeNotConfiguredError("Set REACTIVE_RESUME_API_KEY on the server"), 400),
        (rr.ResumeNotFoundError("No such resume in the API key's account"), 404),
        (rr.ResumeUnavailableError("REACTIVE_RESUME_API_KEY has no read access"), 502),
    ],
)
def test_a_failure_says_what_to_fix(error, status):
    with patch.object(rr, "get_resume", AsyncMock(side_effect=error)):
        response = _client(ADMIN).get("/resumes/r1")
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


def test_an_unexpected_failure_keeps_its_detail_in_the_log():
    with patch.object(
        rr, "list_resumes", AsyncMock(side_effect=RuntimeError("internal detail"))
    ):
        response = _client(ADMIN).get("/resumes")
    assert response.status_code == 502
    assert "internal detail" not in response.text


def test_an_id_past_the_length_cap_is_refused():
    with patch.object(rr, "get_resume", AsyncMock()) as fetch:
        response = _client(ADMIN).get(f"/resumes/{'x' * 65}")
    assert response.status_code == 422
    fetch.assert_not_called()
