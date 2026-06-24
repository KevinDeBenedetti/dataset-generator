"""API tests for the auth routes (login / logout / me)."""

from server.services.users import create_user
from server.models.user import UserRole


def _seed_user(db, email="user@example.com", password="pw12345", role=UserRole.USER):
    return create_user(db, email=email, password=password, role=role)


class TestLogin:
    def test_login_success_sets_cookie(self, client, test_db):
        _seed_user(test_db, email="alice@example.com", password="secret")
        resp = client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "alice@example.com"
        assert data["role"] == "user"
        # httpOnly auth cookie issued.
        set_cookie = resp.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "HttpOnly" in set_cookie

    def test_login_wrong_password(self, client, test_db):
        _seed_user(test_db, email="alice@example.com", password="secret")
        resp = client.post(
            "/auth/login",
            json={"email": "alice@example.com", "password": "nope"},
        )
        assert resp.status_code == 401

    def test_login_unknown_email(self, client, test_db):
        resp = client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "x"},
        )
        assert resp.status_code == 401

    def test_login_invalid_email_is_422(self, client):
        resp = client.post(
            "/auth/login", json={"email": "not-an-email", "password": "x"}
        )
        assert resp.status_code == 422


class TestMeAndLogout:
    def test_me_requires_authentication(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_me_after_login(self, client, test_db):
        _seed_user(test_db, email="bob@example.com", password="secret")
        client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "secret"},
        )
        # TestClient persists the cookie across requests.
        resp = client.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == "bob@example.com"

    def test_logout_clears_cookie(self, client, test_db):
        _seed_user(test_db, email="bob@example.com", password="secret")
        client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "secret"},
        )
        assert client.get("/auth/me").status_code == 200
        assert client.post("/auth/logout").status_code == 204
        # Cookie cleared → no longer authenticated.
        assert client.get("/auth/me").status_code == 401
