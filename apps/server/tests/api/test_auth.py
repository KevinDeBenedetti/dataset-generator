"""API tests for the auth routes (login / refresh / logout / me)."""

import pytest

from server.core.config import config
from server.services.users import create_user
from server.services.rate_limit import login_rate_limiter
from server.models.user import UserRole


@pytest.fixture
def client(auth_client):
    """These tests exercise the real authentication, not a pre-signed-in caller."""
    return auth_client


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
    @pytest.fixture
    def strict_rotation(self, monkeypatch):
        """No reuse grace: any second use of a refresh token is treated as theft."""
        monkeypatch.setattr(config, "auth_refresh_reuse_grace_seconds", 0)

    @staticmethod
    def _present(client, token):
        """Send ``token`` as the refresh cookie — alone: the jar also holds the one
        the last response set, and of two same-named cookies the server reads
        the last."""
        client.cookies.delete(config.auth_refresh_cookie_name)
        client.cookies.set(config.auth_refresh_cookie_name, token)

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

    def test_only_a_sign_in_dates_the_session(self, client, test_db):
        """Deleting the account needs a recent sign-in: a refresh isn't one."""
        self._login(client, test_db)
        assert client.post("/auth/refresh").status_code == 200
        resp = client.delete("/me")
        assert resp.status_code == 403
        assert "Sign in again" in resp.json()["detail"]

        resp = client.post(
            "/auth/login", json={"email": "carol@example.com", "password": "secret"}
        )
        assert resp.status_code == 200
        assert client.delete("/me").status_code == 204
        assert client.get("/auth/me").status_code == 401

    def test_consumed_refresh_token_is_rejected(self, client, test_db, strict_rotation):
        self._login(client, test_db)
        old = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/refresh").status_code == 200

        # Replay the pre-rotation token.
        self._present(client, old)
        assert client.post("/auth/refresh").status_code == 401

    def test_replay_revokes_the_successor_too(self, client, test_db, strict_rotation):
        self._login(client, test_db)
        old = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/refresh").status_code == 200
        successor = client.cookies.get(config.auth_refresh_cookie_name)

        self._present(client, old)
        assert client.post("/auth/refresh").status_code == 401

        # The whole family is dead: the legitimate successor no longer works.
        self._present(client, successor)
        assert client.post("/auth/refresh").status_code == 401

    def test_a_tab_racing_the_rotation_is_not_logged_out(self, client, test_db):
        """Default grace: a second request with the token that was *just* rotated
        (another tab, the Next server) gets its own successor, not a family wipe."""
        self._login(client, test_db)
        old = client.cookies.get(config.auth_refresh_cookie_name)
        first_response = client.post("/auth/refresh")
        assert first_response.status_code == 200
        first = first_response.cookies.get(config.auth_refresh_cookie_name)

        self._present(client, old)
        second_response = client.post("/auth/refresh")
        assert second_response.status_code == 200
        second = second_response.cookies.get(config.auth_refresh_cookie_name)
        assert first and second and second not in (old, first)

        # Both successors are live: neither tab is kicked out.
        for token in (first, second):
            client.cookies.clear()
            self._present(client, token)
            assert client.post("/auth/refresh").status_code == 200

    def test_refresh_is_throttled_per_client(self, client, test_db, monkeypatch):
        from server.services.rate_limit import refresh_rate_limiter

        self._login(client, test_db)
        monkeypatch.setattr(refresh_rate_limiter, "max_attempts", 2)
        refresh_rate_limiter.clear()
        assert client.post("/auth/refresh").status_code == 200
        assert client.post("/auth/refresh").status_code == 200
        blocked = client.post("/auth/refresh")
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1

    def test_refresh_without_cookie_is_401(self, client):
        assert client.post("/auth/refresh").status_code == 401

    def test_a_refused_refresh_clears_both_auth_cookies(self, client):
        """A refresh cookie the server refuses (revoked elsewhere, account
        disabled, replay) is deleted with the access cookie, so the browser
        stops presenting a session that can't be renewed."""
        from server.core.config import config

        client.cookies.set(config.auth_refresh_cookie_name, "revoked-or-garbage")
        response = client.post("/auth/refresh")

        assert response.status_code == 401
        cleared = response.headers.get_list("set-cookie")
        for name in (config.auth_cookie_name, config.auth_refresh_cookie_name):
            assert any(
                c.startswith(f"{name}=") and "Max-Age=0" in c for c in cleared
            ), cleared

    def test_refresh_with_garbage_cookie_is_401(self, client):
        self._present(client, "not-a-real-token")
        assert client.post("/auth/refresh").status_code == 401

    def test_logout_revokes_the_refresh_token(self, client, test_db):
        self._login(client, test_db)
        token = client.cookies.get(config.auth_refresh_cookie_name)
        assert client.post("/auth/logout").status_code == 204

        # Even if the cookie value was captured, it can't renew the session.
        self._present(client, token)
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

    def test_spoofed_forwarded_for_does_not_reset_the_budget(
        self, client, test_db, small_limit
    ):
        """A new X-Forwarded-For per attempt must not count as a new client."""
        _seed_user(test_db, email="alice@example.com", password="secret")
        bad = {"email": "alice@example.com", "password": "wrong"}

        for i in range(3):
            headers = {"X-Forwarded-For": f"203.0.113.{i}"}
            assert (
                client.post("/auth/login", json=bad, headers=headers).status_code == 401
            )

        headers = {"X-Forwarded-For": "203.0.113.99"}
        assert client.post("/auth/login", json=bad, headers=headers).status_code == 429

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


class TestLocalLoginSwitch:
    def test_disabled_login_is_404_and_never_checks_the_password(
        self, client, test_db, monkeypatch
    ):
        _seed_user(test_db, email="zed@example.com", password="secret")
        monkeypatch.setattr(config, "enable_local_login", False)
        response = client.post(
            "/auth/login", json={"email": "zed@example.com", "password": "secret"}
        )
        assert response.status_code == 404
        assert "access_token" not in response.headers.get("set-cookie", "")


class TestAdminLogin:
    """POST /auth/admin/login: the admin, from the deployment's secrets only."""

    PASSWORD = "correct horse battery staple"
    TOTP = "JBSWY3DPEHPK3PXPJBSWY3DP"

    @pytest.fixture(autouse=True)
    def admin_env(self, monkeypatch):
        from server.auth.admin_secrets import hash_password

        monkeypatch.setattr(config, "admin_username", "operator")
        monkeypatch.setattr(config, "admin_password_hash", hash_password(self.PASSWORD))

    def _login(self, client, **overrides):
        body = {"username": "operator", "password": self.PASSWORD, **overrides}
        return client.post("/auth/admin/login", json=body)

    def test_signs_the_admin_in(self, client, test_db):
        resp = self._login(client)
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "admin"
        assert resp.json()["provider"] == "secrets"
        assert client.get("/auth/me").json()["role"] == "admin"
        # The admin's routes answer (the role is in the session).
        assert client.get("/admin/users").status_code == 200

    @pytest.mark.parametrize(
        "overrides",
        [{"password": "wrong"}, {"username": "someone"}, {"otp": "000000"}],
    )
    def test_every_failure_looks_alike(self, client, overrides, monkeypatch):
        if "otp" in overrides:
            monkeypatch.setattr(config, "admin_totp_secret", self.TOTP)
        resp = self._login(client, **overrides)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Incorrect username, password or code"

    def test_the_totp_code_is_asked_for_when_configured(self, client, monkeypatch):
        import time

        from server.auth.admin_secrets import totp_code

        monkeypatch.setattr(config, "admin_totp_secret", self.TOTP)
        assert client.get("/auth/providers").json()["admin_totp"] is True
        assert self._login(client).status_code == 401
        assert (
            self._login(client, otp=totp_code(self.TOTP, time.time())).status_code
            == 200
        )

    def test_five_failures_a_minute_then_429(self, client):
        for _ in range(5):
            assert self._login(client, password="wrong").status_code == 401
        assert self._login(client).status_code == 429

    def test_audits_without_the_submitted_values(self, client, test_db):
        from server.models.identity import AuditLog

        self._login(client, password="leaked-guess-123")
        self._login(client)
        entries = test_db.query(AuditLog).order_by(AuditLog.id).all()
        actions = [e.action for e in entries]
        assert "admin.login.failure" in actions and "admin.login.success" in actions
        dumped = repr([(e.detail, e.actor_label, e.target_label) for e in entries])
        assert "leaked-guess-123" not in dumped and self.PASSWORD not in dumped
        failure = next(e for e in entries if e.action == "admin.login.failure")
        assert failure.ip

    def test_a_rotated_hash_refuses_the_old_password(self, client, monkeypatch):
        from server.auth.admin_secrets import hash_password

        assert self._login(client).status_code == 200
        monkeypatch.setattr(
            config, "admin_password_hash", hash_password("new-one-456789")
        )
        assert self._login(client).status_code == 401
        # The session already open survives until "sign out everywhere".
        assert client.get("/auth/me").status_code == 200

    def test_not_found_without_secrets(self, client, monkeypatch):
        monkeypatch.setattr(config, "admin_username", "")
        assert self._login(client).status_code == 404

    def test_the_admin_is_locked_in_the_backoffice(self, client, test_db):
        admin_id = self._login(client).json()["id"]
        resp = client.patch(f"/admin/users/{admin_id}", json={"is_active": False})
        assert resp.status_code in (400, 409, 422)


class TestHfLogin:
    """POST /auth/hf: a user, with their Hugging Face username and token."""

    TOKEN = "hf_" + "c" * 34

    @pytest.fixture(autouse=True)
    def hub(self, monkeypatch):
        import json
        from pathlib import Path

        from server.auth import hf_token
        from server.services import platform

        fixtures = Path(__file__).resolve().parent.parent / "fixtures" / "hf_whoami"
        self.answers = {
            self.TOKEN: json.loads((fixtures / "write.json").read_text()),
            "hf_" + "r" * 34: json.loads((fixtures / "read.json").read_text()),
        }

        def fetch(token):
            if token not in self.answers:
                raise hf_token.SignInRefused(
                    "token_invalid", "Hugging Face rejected this token"
                )
            return self.answers[token]

        monkeypatch.setattr(hf_token, "whoami_fetcher", fetch)
        monkeypatch.setattr(platform, "signup_policy", lambda: "open")

    def _login(self, client, username="alice", token=None):
        return client.post(
            "/auth/hf", json={"username": username, "token": token or self.TOKEN}
        )

    def test_signs_in_and_never_returns_the_token(self, client):
        resp = self._login(client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "alice" and body["provider"] == "hf"
        assert self.TOKEN not in resp.text
        me = client.get("/auth/me")
        assert me.status_code == 200 and self.TOKEN not in me.text
        secrets = client.get("/me/secrets")
        assert secrets.status_code == 200 and self.TOKEN not in secrets.text

    @pytest.mark.parametrize(
        "username,token,status,code",
        [
            ("bob", None, 401, "token_other_account"),
            ("alice", "hf_" + "r" * 34, 403, "token_read_only"),
            ("alice", "hf_" + "z" * 34, 401, "token_invalid"),
            ("alice", "not-a-token", 401, "token_malformed"),
        ],
    )
    def test_each_refusal_has_its_code(self, client, username, token, status, code):
        resp = self._login(client, username, token)
        assert resp.status_code == status
        assert resp.json()["code"] == code

    def test_refusals_are_translated(self, client):
        resp = client.post(
            "/auth/hf",
            json={"username": "bob", "token": self.TOKEN},
            headers={"Accept-Language": "fr"},
        )
        assert resp.json()["detail"] == "Ce jeton appartient à un autre compte"

    def test_closed_sign_up_refuses_a_new_account(self, client, monkeypatch):
        from server.services import platform

        monkeypatch.setattr(platform, "signup_policy", lambda: "closed")
        resp = self._login(client)
        assert resp.status_code == 403 and resp.json()["code"] == "signup_closed"

    def test_ten_failures_a_minute_then_429(self, client):
        for _ in range(10):
            assert self._login(client, token="hf_" + "z" * 34).status_code == 401
        assert self._login(client).status_code == 429

    def test_a_hub_outage_answers_503(self, client, monkeypatch):
        from server.auth import hf_token

        def down(_token):
            raise hf_token.HubUnavailable()

        monkeypatch.setattr(hf_token, "whoami_fetcher", down)
        resp = self._login(client)
        assert resp.status_code == 503 and resp.json()["code"] == "hub_unavailable"
