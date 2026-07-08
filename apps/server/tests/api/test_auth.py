"""API tests for the auth routes (login / refresh / logout / me)."""

import pytest

from server.core.config import config
from server.services.users import create_user
from server.services.rate_limit import login_rate_limiter
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


class TestRefresh:
    def _login(self, client, test_db, email="carol@example.com", password="secret"):
        _seed_user(test_db, email=email, password=password)
        resp = client.post("/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200
        return resp

    def test_login_sets_refresh_cookie(self, client, test_db):
        self._login(client, test_db)
        assert client.cookies.get(config.auth_refresh_cookie_name)
        assert client.cookies.get(config.auth_cookie_name)

    def test_refresh_rotates_and_returns_user(self, client, test_db):
        self._login(client, test_db)
        before = client.cookies.get(config.auth_refresh_cookie_name)

        resp = client.post("/auth/refresh")
        assert resp.status_code == 200
        assert resp.json()["email"] == "carol@example.com"
        after = client.cookies.get(config.auth_refresh_cookie_name)
        assert after and after != before
        # The new access token authenticates.
        assert client.get("/auth/me").status_code == 200

    def test_consumed_refresh_token_is_rejected(self, client, test_db):
        self._login(client, test_db)
        old = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/refresh").status_code == 200

        # Replay the pre-rotation token.
        client.cookies.set(config.auth_refresh_cookie_name, old)
        assert client.post("/auth/refresh").status_code == 401

    def test_replay_revokes_the_successor_too(self, client, test_db):
        self._login(client, test_db)
        old = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/refresh").status_code == 200
        successor = client.cookies.get(config.auth_refresh_cookie_name)

        client.cookies.set(config.auth_refresh_cookie_name, old)
        assert client.post("/auth/refresh").status_code == 401

        # The whole family is dead: the legitimate successor no longer works.
        client.cookies.set(config.auth_refresh_cookie_name, successor)
        assert client.post("/auth/refresh").status_code == 401

    def test_refresh_without_cookie_is_401(self, client):
        assert client.post("/auth/refresh").status_code == 401

    def test_refresh_with_garbage_cookie_is_401(self, client):
        client.cookies.set(config.auth_refresh_cookie_name, "not-a-real-token")
        assert client.post("/auth/refresh").status_code == 401

    def test_logout_revokes_the_refresh_token(self, client, test_db):
        self._login(client, test_db)
        token = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/logout").status_code == 204

        # Even if the cookie value was captured, it can't renew the session.
        client.cookies.set(config.auth_refresh_cookie_name, token)
        assert client.post("/auth/refresh").status_code == 401


class TestLoginRateLimit:
    @pytest.fixture
    def small_limit(self):
        """Shrink the limiter to 3 attempts for a fast test, then restore."""
        original = login_rate_limiter.max_attempts
        login_rate_limiter.max_attempts = 3
        login_rate_limiter.clear()
        yield
        login_rate_limiter.max_attempts = original
        login_rate_limiter.clear()

    def test_too_many_failures_returns_429(self, client, test_db, small_limit):
        _seed_user(test_db, email="alice@example.com", password="secret")
        bad = {"email": "alice@example.com", "password": "wrong"}

        # First 3 failures are plain 401s.
        for _ in range(3):
            assert client.post("/auth/login", json=bad).status_code == 401

        # The 4th is throttled with a Retry-After header.
        blocked = client.post("/auth/login", json=bad)
        assert blocked.status_code == 429
        assert "retry-after" in {k.lower() for k in blocked.headers}

        # Even the correct password is blocked while throttled.
        good = {"email": "alice@example.com", "password": "secret"}
        assert client.post("/auth/login", json=good).status_code == 429

    def test_successful_login_resets_counter(self, client, test_db, small_limit):
        _seed_user(test_db, email="alice@example.com", password="secret")
        bad = {"email": "alice@example.com", "password": "wrong"}
        good = {"email": "alice@example.com", "password": "secret"}

        # Two failures (under the cap), then a success clears the counter...
        assert client.post("/auth/login", json=bad).status_code == 401
        assert client.post("/auth/login", json=bad).status_code == 401
        assert client.post("/auth/login", json=good).status_code == 200

        # ...so the budget is full again: three more failures stay 401, not 429.
        for _ in range(3):
            assert client.post("/auth/login", json=bad).status_code == 401
