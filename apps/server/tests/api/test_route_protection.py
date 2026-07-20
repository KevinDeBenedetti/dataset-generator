"""Verify feature routers reject unauthenticated requests.

Main mounts the feature routers with ``dependencies=[Depends(get_current_user)]``.
This rebuilds that wiring for the dataset router and checks both sides: a
request without a valid token is rejected (401), and one with an authenticated
user passes through.
"""

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from server.api import collections, dataset, generate, quality_rules
from server.core.database import get_db
from server.models.user import User, UserRole
from server.services.auth import get_current_user


def _build_protected_app(test_db):
    app = FastAPI()
    auth_required = [Depends(get_current_user)]
    app.include_router(dataset.router, dependencies=auth_required)
    app.include_router(generate.router, dependencies=auth_required)
    app.include_router(collections.router, dependencies=auth_required)
    app.include_router(quality_rules.router, dependencies=auth_required)

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


# Destructive/costly routes are additionally gated behind require_admin.
_ADMIN_ONLY_ROUTES = [
    ("delete", "/dataset/my_dataset"),
    ("post", "/dataset/my_dataset/clean-similarities"),
    ("post", "/dataset/my_dataset/resolve-pair"),
    ("post", "/collections/my_dataset/qdrant"),
    ("put", "/quality-rules"),
]


def test_admin_routes_reject_non_admin(test_db):
    app = _build_protected_app(test_db)

    # An authenticated but non-admin user resolves through get_current_user.
    regular_user = User(id="u1", email="user@example.com", role=UserRole.USER)
    app.dependency_overrides[get_current_user] = lambda: regular_user

    client = TestClient(app)
    for method, path in _ADMIN_ONLY_ROUTES:
        response = getattr(client, method)(path)
        assert response.status_code == 403, f"{method} {path} should be admin-only"


def test_admin_routes_allow_admin(test_db):
    app = _build_protected_app(test_db)

    admin_user = User(id="a1", email="admin@example.com", role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = lambda: admin_user

    client = TestClient(app)
    # Past the admin gate the handlers run; mock their service layer so we assert
    # the gate (200), not the Langfuse/Qdrant side effects.
    with patch(
        "server.api.dataset.delete_dataset_view",
        return_value={
            "message": "deleted",
            "dataset_id": "my_dataset",
            "records_deleted": 0,
        },
    ):
        assert client.delete("/dataset/my_dataset").status_code == 200
    with patch(
        "server.api.dataset.clean_similarities_view",
        return_value={
            "dataset_id": "my_dataset",
            "dataset_name": "my_dataset",
            "threshold": 0.8,
            "total_records": 0,
            "removed_records": 0,
            "details": [],
            "removed_items": [],
        },
    ):
        assert client.post("/dataset/my_dataset/clean-similarities").status_code == 200
    with patch(
        "server.api.dataset.resolve_similarity_pair",
        return_value={
            "dataset_id": "my_dataset",
            "dataset_name": "my_dataset",
            "removed_id": "aaaa1111",
            "removed_question": "What is Python?",
        },
    ):
        assert (
            client.post(
                "/dataset/my_dataset/resolve-pair", json={"remove_id": "aaaa1111"}
            ).status_code
            == 200
        )
    with patch(
        "server.api.quality_rules.update_quality_rules",
        return_value={
            "min_answer_words": 5,
            "reject_below_confidence": 0.5,
            "auto_reject_enabled": True,
            "updated_at": None,
        },
    ):
        assert (
            client.put(
                "/quality-rules", json={"min_answer_words": 5}
            ).status_code
            == 200
        )
