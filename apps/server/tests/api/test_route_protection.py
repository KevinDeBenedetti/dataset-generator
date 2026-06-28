"""Verify feature routers reject unauthenticated requests.

Main mounts the feature routers with ``dependencies=[Depends(get_current_user)]``.
This rebuilds that wiring for the dataset router and checks both sides: a
request without a valid token is rejected (401), and one with an authenticated
user passes through.
"""

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.api import collections, dataset, generate
from server.core.database import get_db
from server.models.user import User, UserRole
from server.services.auth import get_current_user


def _build_protected_app(test_db):
    app = FastAPI()
    auth_required = [Depends(get_current_user)]
    app.include_router(dataset.router, dependencies=auth_required)
    app.include_router(generate.router, dependencies=auth_required)
    app.include_router(collections.router, dependencies=auth_required)

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_protected_routes_reject_anonymous(test_db):
    app = _build_protected_app(test_db)
    client = TestClient(app)

    # No auth cookie / header → 401 on every feature route.
    assert client.get("/dataset").status_code == 401
    assert client.get("/collections").status_code == 401
    assert (
        client.post(
            "/dataset/generate",
            json={"url": "https://example.com", "dataset_name": "x"},
        ).status_code
        == 401
    )


def test_protected_routes_allow_authenticated(test_db):
    app = _build_protected_app(test_db)

    # Inject an authenticated user the way a valid cookie would resolve one.
    fake_user = User(id="u1", email="user@example.com", role=UserRole.USER)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    client = TestClient(app)

    # The dataset list now passes the auth gate and returns 200. The list comes
    # from Langfuse (mocked here) — the point of this test is the auth gate.
    with patch("server.api.dataset.list_datasets_view", return_value=[]):
        response = client.get("/dataset")
    assert response.status_code == 200
    assert response.json() == []
