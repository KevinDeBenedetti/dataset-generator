"""The backoffice, on the real app: admins only, accounts and usage only."""

import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.core.config import config
from server.core.database import get_db
from server.main import create_app
from server.models.identity import AuditLog, Identity
from server.models.user import User, UserRole
from server.services import platform
from server.services.auth import create_access_token
from server.services.datasets import save_generation
from server.services.user_secrets import set_secret
from server.services.users import create_user

SECRET_NAME = "bobs-private-dataset"
CANARY = "sk-canary-0123456789abcdefABCDEF"
FRONT = "http://localhost:3000"


@pytest.fixture(autouse=True)
def _stores(monkeypatch, datasets_db):
    """Every service that opens its own session uses the test database."""
    for module in ("platform", "quality_rules", "model_defaults", "jobs"):
        monkeypatch.setattr(f"server.services.{module}.get_scoped_db", datasets_db)
    monkeypatch.setattr(config, "admin_emails_raw", "")
    monkeypatch.setattr(config, "frontend_url", FRONT)
    platform.clear_cache()
    yield
    platform.clear_cache()


@pytest.fixture
def app(test_db):
    application = create_app()
    application.dependency_overrides[get_db] = lambda: test_db
    return application


def _as(app, user):
    client = TestClient(app, base_url="http://testserver", headers={"Origin": FRONT})
    if user is not None:
        client.cookies.set(config.auth_cookie_name, create_access_token(user))
    return client


@pytest.fixture
def root(test_db):
    return create_user(
        test_db, email="root@test.local", password="pw12345", role=UserRole.ADMIN
    )


@pytest.fixture
def bob(test_db):
    user = create_user(test_db, email="bob@test.local", password="pw12345")
    save_generation(
        user.id,
        SECRET_NAME,
        [
            {
                "id": "p1",
                "question": "What is Bob's secret?",
                "answer": "Nobody knows.",
                "context": "c",
                "source_url": "https://example.com",
                "confidence": 0.9,
                "metadata": {},
            }
        ],
        source_url="https://example.com",
    )
    set_secret(user.id, "openai_api_key", CANARY)
    return user


def _admin_routes(app):
    return [
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/admin")
        for method in ops
    ]


def test_every_admin_route_refuses_non_admins(app, bob):
    routes = _admin_routes(app)
    assert len(routes) >= 7
    anonymous, user = _as(app, None), _as(app, bob)
    for method, path in routes:
        url = path.replace("{user_id}", bob.id)
        assert anonymous.request(method, url, json={}).status_code == 401, (
            method,
            path,
        )
        assert user.request(method, url, json={}).status_code == 403, (method, path)


def test_the_user_list_shows_counts_never_content_or_secrets(app, root, bob):
    response = _as(app, root).get("/admin/users")

    assert response.status_code == 200
    assert SECRET_NAME not in response.text
    assert "Bob's secret" not in response.text
    assert CANARY not in response.text and CANARY[-4:] not in response.text
    row = next(u for u in response.json()["users"] if u["email"] == "bob@test.local")
    assert (row["datasets"], row["pairs"], row["runs"]) == (1, 1, 0)
    assert row["configured_keys"] == ["openai_api_key"]
    assert row["role"] == "user" and row["locked"] is False


def test_search_and_pagination(app, root, bob):
    client = _as(app, root)
    assert [u["email"] for u in client.get("/admin/users?q=BOB").json()["users"]] == [
        "bob@test.local"
    ]
    page = client.get("/admin/users?limit=1").json()
    assert page["total"] == 2 and len(page["users"]) == 1


def test_role_changes_are_audited(app, root, bob, test_db):
    client = _as(app, root)
    promoted = client.patch(f"/admin/users/{bob.id}", json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"

    entry = test_db.scalar(
        select(AuditLog).where(AuditLog.action == "user.role_changed")
    )
    assert (entry.actor_id, entry.target_user_id) == (root.id, bob.id)
    assert entry.detail == {"from": "user", "to": "admin"}


def test_the_last_admin_cannot_be_demoted_deactivated_or_deleted(app, root, bob):
    client = _as(app, root)
    for body in ({"role": "user"}, {"is_active": False}):
        response = client.patch(f"/admin/users/{root.id}", json=body)
        assert response.status_code == 409, body
        assert "last active admin" in response.json()["detail"]

    # With a second admin, one of them may step down.
    client.patch(f"/admin/users/{bob.id}", json={"role": "admin"})
    assert (
        client.patch(f"/admin/users/{root.id}", json={"role": "user"}).status_code
        == 200
    )


def test_admin_emails_accounts_are_locked(app, root, test_db, monkeypatch):
    boss = create_user(
        test_db, email="boss@test.local", password="pw12345", role=UserRole.ADMIN
    )
    monkeypatch.setattr(config, "admin_emails_raw", "boss@test.local")
    client = _as(app, root)

    assert client.get(f"/admin/users/{boss.id}").json()["locked"] is True
    for body in ({"role": "user"}, {"is_active": False}):
        assert client.patch(f"/admin/users/{boss.id}", json=body).status_code == 409
    assert client.delete(f"/admin/users/{boss.id}").status_code == 409


def test_deactivating_signs_the_user_out_at_once(app, root, bob, test_db):
    bobs_client = _as(app, bob)
    assert bobs_client.get("/auth/me").status_code == 200

    assert (
        _as(app, root)
        .patch(f"/admin/users/{bob.id}", json={"is_active": False})
        .status_code
        == 200
    )

    assert bobs_client.get("/auth/me").status_code == 401
    assert (
        _as(app, root)
        .patch(f"/admin/users/{bob.id}", json={"is_active": True})
        .json()["is_active"]
    )


def test_deleting_a_user_removes_their_data_and_collections(app, root, bob, test_db):
    with patch("server.services.qdrant.delete_collection", return_value=True) as drop:
        response = _as(app, root).delete(f"/admin/users/{bob.id}")

    assert response.status_code == 204
    drop.assert_called_once()
    test_db.expire_all()
    assert test_db.get(User, bob.id) is None
    entry = test_db.scalar(select(AuditLog).where(AuditLog.action == "user.deleted"))
    assert entry.target_label.startswith("email:")  # still readable afterwards
    if test_db.bind.dialect.name == "postgresql":  # FK ON DELETE SET NULL
        assert entry.target_user_id is None
    assert entry.actor_id == root.id


def test_an_admin_deletes_their_own_account_from_settings_not_here(app, root):
    assert _as(app, root).delete(f"/admin/users/{root.id}").status_code == 409
    assert _as(app, root).get("/admin/users/nope").status_code == 404


def test_platform_switches_override_and_reset_the_env(app, root, test_db, monkeypatch):
    monkeypatch.setattr(config, "allow_signup", True)
    client = _as(app, root)
    switches = {s["key"]: s for s in client.get("/admin/platform").json()["settings"]}
    assert switches["allow_signup"] == {
        "key": "allow_signup",
        "label": switches["allow_signup"]["label"],
        "value": True,
        "overridden": False,
    }

    saved = client.put(
        "/admin/platform",
        json={
            "settings": {
                "allow_signup": False,
                "allowed_email_domains": ["@Corp.Example"],
            }
        },
    )
    assert saved.status_code == 200
    by_key = {s["key"]: s for s in saved.json()["settings"]}
    assert (
        by_key["allow_signup"]["value"] is False
        and by_key["allow_signup"]["overridden"]
    )
    assert by_key["allowed_email_domains"]["value"] == ["corp.example"]
    assert platform.allow_signup() is False
    assert _as(app, None).get("/auth/providers").json()["signup_open"] is False

    reset = client.put("/admin/platform", json={"settings": {"allow_signup": None}})
    assert {s["key"]: s for s in reset.json()["settings"]}["allow_signup"][
        "overridden"
    ] is False
    assert test_db.scalar(select(AuditLog).where(AuditLog.action == "platform.updated"))


@pytest.mark.parametrize(
    "settings",
    [
        {"allow_signup": "yes"},
        {"allowed_llm_hosts": ["not a host"]},
        {"allowed_llm_hosts": "gateway.example.com"},
        {"nope": True},
    ],
)
def test_invalid_platform_values_are_refused(app, root, settings):
    response = _as(app, root).put("/admin/platform", json={"settings": settings})
    assert response.status_code == 422


def test_an_allowed_host_becomes_usable_as_a_base_url(app, root, bob, monkeypatch):
    from server.services.providers.openai import check_base_url

    with pytest.raises(ValueError):
        check_base_url("https://gateway.example.com/v1")
    _as(app, root).put(
        "/admin/platform",
        json={"settings": {"allowed_llm_hosts": ["gateway.example.com"]}},
    )
    assert check_base_url("https://gateway.example.com/v1")


def test_audit_log_and_usage(app, root, bob):
    client = _as(app, root)
    client.patch(f"/admin/users/{bob.id}", json={"role": "admin"})

    audit = client.get(f"/admin/audit?user_id={bob.id}").json()
    assert [e["action"] for e in audit["entries"]] == ["user.role_changed"]
    assert audit["entries"][0]["actor"] == "root@test.local"

    usage = client.get("/admin/usage").json()
    assert usage["users"]["total"] == 2 and usage["users"]["admins"] == 2
    assert (usage["datasets"], usage["pairs"], usage["running"]) == (1, 1, 0)


def test_export_contains_your_data_but_not_your_keys(app, bob):
    response = _as(app, bob).get("/me/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert {"account.json", "settings.json", f"datasets/{SECRET_NAME}.jsonl"} <= names
    [pair] = [
        json.loads(line)
        for line in archive.read(f"datasets/{SECRET_NAME}.jsonl").splitlines()
    ]
    assert pair["question"] == "What is Bob's secret?"
    settings = json.loads(archive.read("settings.json"))
    assert settings["keys_saved"] == ["openai_api_key"]
    everything = b"".join(archive.read(n) for n in names)
    assert CANARY.encode() not in everything


def test_deleting_your_own_account(app, bob, test_db):
    client = _as(app, bob)
    with patch("server.services.qdrant.delete_collection", return_value=True):
        assert client.delete("/me").status_code == 204
    test_db.expire_all()
    assert test_db.get(User, bob.id) is None
    assert test_db.scalar(select(Identity)) is None


def test_the_last_admin_cannot_delete_their_own_account(app, root):
    assert _as(app, root).delete("/me").status_code == 409
