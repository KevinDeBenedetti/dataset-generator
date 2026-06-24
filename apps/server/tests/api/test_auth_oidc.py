"""API tests for the OIDC login/callback routes (provider calls mocked)."""

from unittest.mock import AsyncMock, MagicMock, patch

from server.core.config import config
from server.models.user import User


class TestOidcGating:
    def test_login_503_when_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "")
        monkeypatch.setattr(config, "oidc_client_id", "")
        monkeypatch.setattr(config, "oidc_client_secret", "")
        resp = client.get("/auth/oidc/login")
        assert resp.status_code == 503

    def test_callback_503_when_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "")
        monkeypatch.setattr(config, "oidc_client_id", "")
        monkeypatch.setattr(config, "oidc_client_secret", "")
        resp = client.get("/auth/oidc/callback")
        assert resp.status_code == 503


class TestOidcCallback:
    def _configure(self, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "https://login.infomaniak.com")
        monkeypatch.setattr(config, "oidc_client_id", "cid")
        monkeypatch.setattr(config, "oidc_client_secret", "secret")

    def test_callback_creates_user_and_sets_cookie(self, client, test_db, monkeypatch):
        self._configure(monkeypatch)

        # Mock Authlib: create_client(...).authorize_access_token(...) → token
        fake_client = MagicMock()
        fake_client.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"sub": "abc-123", "email": "oidc@example.com"}}
        )
        fake_oauth = MagicMock()
        fake_oauth.create_client.return_value = fake_client

        with patch("server.api.auth.get_oauth", return_value=fake_oauth):
            resp = client.get("/auth/oidc/callback", follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["location"] == config.frontend_url
        assert "access_token=" in resp.headers.get("set-cookie", "")

        # The user was provisioned.
        user = test_db.query(User).filter(User.oidc_sub == "abc-123").first()
        assert user is not None
        assert user.email == "oidc@example.com"

    def test_callback_400_when_no_subject(self, client, monkeypatch):
        self._configure(monkeypatch)

        fake_client = MagicMock()
        fake_client.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "x@example.com"}}  # no 'sub'
        )
        fake_oauth = MagicMock()
        fake_oauth.create_client.return_value = fake_client

        with patch("server.api.auth.get_oauth", return_value=fake_oauth):
            resp = client.get("/auth/oidc/callback", follow_redirects=False)
        assert resp.status_code == 400
