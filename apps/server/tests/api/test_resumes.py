"""The /resumes routes: admins only, errors answered with what to fix, and
each resume's dataset settings and runs.

The service is mocked: tests/services/test_reactive_resume.py covers the
instance. ``_client`` keeps the real ``require_admin``, so the role check is
the real one; the dataset routes run on the test database (``client_for``),
the schedules and runs themselves are tests/services/test_schedules.py's.
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


# --- a resume's dataset -------------------------------------------------------------

VIEW = {
    "id": "r1",
    "name": "Engineer",
    "slug": "engineer",
    "basics": {"name": "Kevin"},
    "summary": "",
    "sections": [],
}
SETTINGS = {
    "target_repo": "kevin/resume-qa",
    "language": "fr",
    "every": "week",
    "at_hour": 6,
    "at_minute": 30,
}


@pytest.fixture
def admin_client(test_db, client_for, datasets_db, monkeypatch):
    from server.services.users import create_user

    # The runs and the saved model are on the test database too (they stay
    # unreachable unless a test hands them one, see tests/conftest.py).
    for target in (
        "server.services.jobs.get_scoped_db",
        "server.services.model_defaults.get_scoped_db",
    ):
        monkeypatch.setattr(target, datasets_db)
    admin = create_user(
        test_db, email="admin@test.local", password="pw12345", role=UserRole.ADMIN
    )
    return client_for(admin)


def test_the_dataset_routes_are_for_admins_only_too():
    client = _client(USER)
    with patch.object(rr, "get_resume", AsyncMock(return_value=VIEW)) as fetch:
        assert client.get("/resumes/r1/dataset").status_code == 403
        assert client.put("/resumes/r1/dataset", json=SETTINGS).status_code == 403
        assert client.delete("/resumes/r1/dataset").status_code == 403
        assert client.post("/resumes/r1/dataset/run", json={}).status_code == 403
    fetch.assert_not_called()


def test_the_settings_are_saved_read_and_forgotten(admin_client):
    client = admin_client
    assert client.get("/resumes/r1/dataset").status_code == 404

    with patch.object(rr, "get_resume", AsyncMock(return_value=VIEW)):
        saved = client.put("/resumes/r1/dataset", json=SETTINGS)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["resume_id"] == "r1" and body["title"] == "Engineer"
    assert (body["target_repo"], body["language"], body["every"]) == (
        "kevin/resume-qa",
        "fr",
        "week",
    )
    # A scheduled run publishes what passes, unless told otherwise.
    assert body["publish"] is True
    assert body["next_run_at"] is not None and body["latest_run"] is None
    assert client.get("/resumes/r1/dataset").json()["at_minute"] == 30

    assert client.delete("/resumes/r1/dataset").status_code == 204
    assert client.get("/resumes/r1/dataset").status_code == 404
    assert client.delete("/resumes/r1/dataset").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"target_repo": "not a repo"},
        {"every": "hour"},
        {"at_hour": 24},
        {"language": "de"},
    ],
)
def test_bad_settings_are_refused(admin_client, change):
    with patch.object(rr, "get_resume", AsyncMock(return_value=VIEW)):
        response = admin_client.put("/resumes/r1/dataset", json={**SETTINGS, **change})
    assert response.status_code == 422


def test_settings_for_a_resume_that_is_gone_are_refused(admin_client):
    gone = AsyncMock(side_effect=rr.ResumeNotFoundError("No such resume"))
    with patch.object(rr, "get_resume", gone):
        response = admin_client.put("/resumes/r9/dataset", json=SETTINGS)
    assert response.status_code == 404
    assert admin_client.get("/resumes/r9/dataset").status_code == 404


def test_an_unknown_model_is_refused_when_saved(admin_client):
    with patch.object(rr, "get_resume", AsyncMock(return_value=VIEW)):
        response = admin_client.put(
            "/resumes/r1/dataset", json={**SETTINGS, "model_ref": "openai:nope"}
        )
    assert response.status_code == 400
    assert "Unknown model" in response.json()["detail"]


def test_a_run_uses_the_saved_settings_and_stops_at_a_draft(admin_client):
    client = admin_client
    assert client.post("/resumes/r1/dataset/run", json={}).status_code == 404
    with patch.object(rr, "get_resume", AsyncMock(return_value=VIEW)):
        client.put("/resumes/r1/dataset", json=SETTINGS)

    started = client.post("/resumes/r1/dataset/run", json={"full_refresh": True})

    assert started.status_code == 202, started.text
    run = started.json()
    assert run["job"] == "resume-qa" and run["status"] == "queued"
    assert run["options"]["resume_id"] == "r1"
    assert run["options"]["language"] == "fr"
    assert run["options"]["full_refresh"] is True
    assert run["options"]["publish"] is False  # a run you start: a draft
    assert client.get("/resumes/r1/dataset").json()["latest_run"] == {
        "id": run["id"],
        "status": "queued",
    }
    # One run of the job at a time.
    assert client.post("/resumes/r1/dataset/run", json={}).status_code == 409
