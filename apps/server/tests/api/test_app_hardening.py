"""The real application factory under production and development settings."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from server.core.config import config
from server.main import create_app


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(config, "environment", "production")
    monkeypatch.setattr(config, "docs_enabled", False)
    monkeypatch.setattr(config, "auth_cookie_secure", True)
    monkeypatch.setattr(config, "frontend_url", "https://app.example.com")
    monkeypatch.setattr(config, "enable_local_login", False)
    return TestClient(create_app(), base_url="https://app.example.com")


class TestProduction:
    def test_docs_and_schema_are_not_served(self, production):
        assert production.get("/docs").status_code == 404
        assert production.get("/openapi.json").status_code == 404
        assert production.get("/redoc").status_code == 404

    def test_root_does_not_redirect_to_docs(self, production):
        response = production.get("/", follow_redirects=False)
        assert response.status_code == 200

    def test_security_headers_including_hsts(self, production):
        response = production.get("/health")
        assert response.headers["x-frame-options"] == "DENY"
        assert "max-age=" in response.headers["strict-transport-security"]

    def test_cross_origin_post_is_rejected_before_any_handler(self, production):
        response = production.post(
            "/auth/login",
            json={"email": "a@b.co", "password": "x"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403

    def test_local_login_is_disabled(self, production):
        response = production.post(
            "/auth/login",
            json={"email": "a@b.co", "password": "x"},
            headers={"Origin": "https://app.example.com"},
        )
        assert response.status_code == 404

    def test_cors_is_narrow(self, production):
        response = production.options(
            "/auth/me",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "TRACE",
            },
        )
        allowed = response.headers.get("access-control-allow-methods", "")
        assert "TRACE" not in allowed and "*" not in allowed


class TestProbes:
    def test_health_is_static_and_never_asks_the_database(self, production):
        with patch("server.main.database_ready", side_effect=AssertionError("db")):
            response = production.get("/health")
        assert response.status_code == 200 and response.json() == {"status": "ok"}

    def test_ready_is_503_while_the_database_is_down(self, production):
        with patch("server.main.database_ready", return_value=False):
            ready = production.get("/ready")
            health = production.get("/health")
        assert ready.status_code == 503
        assert health.status_code == 200  # liveness must survive a DB blip

    def test_ready_is_200_when_the_database_answers(self, production):
        with patch("server.main.database_ready", return_value=True):
            assert production.get("/ready").status_code == 200


class TestDevelopment:
    def test_docs_stay_available(self, monkeypatch):
        monkeypatch.setattr(config, "docs_enabled", True)
        client = TestClient(create_app())
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/", follow_redirects=False).status_code == 302

    def test_no_hsts_over_plain_http(self, monkeypatch):
        monkeypatch.setattr(config, "auth_cookie_secure", False)
        response = TestClient(create_app()).get("/health")
        assert "strict-transport-security" not in response.headers


def test_the_oauth_state_cookie_uses_a_derived_key_and_a_short_life(monkeypatch):
    monkeypatch.setattr(config, "environment", "production")
    monkeypatch.setattr(config, "auth_secret_key", "a" * 48)
    app = create_app()
    session = next(m for m in app.user_middleware if m.cls is SessionMiddleware)
    # Derived from AUTH_SECRET_KEY, never the JWT key itself.
    assert session.kwargs["secret_key"] == config.effective_session_secret
    assert session.kwargs["secret_key"] != config.auth_secret_key
    monkeypatch.setattr(config, "auth_secret_key", "b" * 48)
    assert config.effective_session_secret != session.kwargs["secret_key"]
    assert session.kwargs["max_age"] == 600
    assert session.kwargs["session_cookie"] == "__Host-session"


class TestStartup:
    """The lifespan: unsafe production config refuses to boot; migrations are optional."""

    @pytest.fixture
    def quiet(self, monkeypatch):
        """Everything the lifespan touches except the behaviour under test."""
        import server.main as main_module

        monkeypatch.setattr(main_module, "ensure_secret_is_safe", lambda: None)
        monkeypatch.setattr(main_module, "_purge_expired_refresh_tokens", lambda: None)
        monkeypatch.setattr(config, "seed_dev_users", False)
        upgrade = patch.object(main_module, "upgrade_db")
        with upgrade as mock:
            yield mock

    def test_unsafe_production_config_refuses_to_boot(self, quiet, monkeypatch):
        monkeypatch.setattr(config, "environment", "production")
        monkeypatch.setattr(config, "secrets_encryption_keys_raw", "")
        with pytest.raises(RuntimeError, match="SECRETS_ENCRYPTION_KEYS"):
            with TestClient(create_app()):
                pass
        quiet.assert_not_called()  # it never got as far as the database

    def test_development_boots_with_permissive_settings(self, quiet, monkeypatch):
        monkeypatch.setattr(config, "environment", "development")
        monkeypatch.setattr(config, "auth_cookie_secure", False)
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
        quiet.assert_called_once()

    def test_migrations_run_at_startup_by_default(self, quiet, monkeypatch):
        monkeypatch.setattr(config, "environment", "development")
        monkeypatch.setattr(config, "run_migrations_on_startup", True)
        with TestClient(create_app()):
            pass
        quiet.assert_called_once()

    def test_migrations_can_be_left_to_the_deployment(self, quiet, monkeypatch):
        monkeypatch.setattr(config, "environment", "development")
        monkeypatch.setattr(config, "run_migrations_on_startup", False)
        with TestClient(create_app()):
            pass
        quiet.assert_not_called()
