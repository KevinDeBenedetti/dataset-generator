"""SSO routes end to end, on the real app: Infomaniak (OIDC) and GitHub (OAuth 2).

The provider's token endpoint and API are faked; the state, PKCE and session
cookie handling are Authlib's real ones.
"""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server.core.config import config
from server.core.database import get_db
from server.main import create_app
from server.models.identity import Identity
from server.models.user import User, UserRole
from server.services import sso
from server.services.auth import create_access_token
from server.services.users import create_user

FRONT = "http://localhost:3000"


@pytest.fixture(autouse=True)
def _sso_config(monkeypatch):
    monkeypatch.setattr(config, "github_client_id", "gh-client")
    monkeypatch.setattr(config, "github_client_secret", "gh-secret")
    monkeypatch.setattr(
        config, "github_redirect_uri", "http://testserver/auth/github/callback"
    )
    monkeypatch.setattr(config, "infomaniak_issuer", "")
    monkeypatch.setattr(config, "frontend_url", FRONT)
    monkeypatch.setattr(config, "allow_signup", True)
    monkeypatch.setattr(config, "admin_emails_raw", "")
    monkeypatch.setattr(config, "sso_trusted_email_providers_raw", "infomaniak,github")
    sso.reset_oauth_cache()
    yield
    sso.reset_oauth_cache()


@pytest.fixture
def app(test_db):
    application = create_app()
    application.dependency_overrides[get_db] = lambda: test_db
    return application


@pytest.fixture
def web(app):
    return TestClient(app, base_url="http://testserver")


def _github_api(monkeypatch, user=None, emails=None, token_error=None):
    """Fake GitHub's token endpoint and API on the real Authlib client."""
    client = sso.get_client(sso.PROVIDERS["github"])
    seen = {}

    async def fetch_access_token(**params):
        seen.update(params)
        if token_error:
            raise token_error
        return {"access_token": "gho_x", "token_type": "bearer"}

    responses = {
        "user": user if user is not None else {"id": 4242, "login": "dev"},
        "user/emails": emails
        if emails is not None
        else [{"email": "dev@example.com", "primary": True, "verified": True}],
    }

    async def get(path, token=None, **kw):
        response = MagicMock()
        response.json.return_value = responses[path]
        return response

    monkeypatch.setattr(client, "fetch_access_token", fetch_access_token)
    monkeypatch.setattr(client, "get", get)
    return seen


def _start(web, path="/auth/github/login"):
    response = web.get(path, follow_redirects=False)
    assert response.status_code == 302, response.text
    return parse_qs(urlsplit(response.headers["location"]).query)


def test_providers_lists_only_switches(web):
    body = web.get("/auth/providers").json()
    by_name = {p["name"]: p for p in body["providers"]}
    assert by_name["github"] == {
        "name": "github",
        "label": "GitHub",
        "configured": True,
    }
    assert by_name["infomaniak"]["configured"] is False
    assert set(body) == {"providers", "local_login", "signup_open"}
    assert "gh-secret" not in str(body)


def test_login_redirects_to_github_with_state_and_pkce(web):
    query = _start(web)
    assert query["client_id"] == ["gh-client"]
    assert query["redirect_uri"] == ["http://testserver/auth/github/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0] and query["state"][0]
    assert "read:user" in query["scope"][0] and "user:email" in query["scope"][0]


def test_a_full_github_sign_in_creates_the_account_and_signs_in(
    web, test_db, monkeypatch
):
    seen = _github_api(monkeypatch)
    state = _start(web)["state"][0]

    response = web.get(
        f"/auth/github/callback?code=abc&state={state}", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONT}/dashboard"
    assert config.auth_cookie_name in response.cookies
    # PKCE: the verifier matching the challenge went to the token endpoint.
    assert seen["code"] == "abc" and seen.get("code_verifier")
    identity = test_db.scalar(select(Identity))
    assert (identity.provider, identity.subject, identity.username) == (
        "github",
        "4242",
        "dev",
    )
    assert test_db.get(User, identity.user_id).email == "dev@example.com"


def test_a_tampered_state_is_refused(web, test_db, monkeypatch):
    _github_api(monkeypatch)
    _start(web)
    response = web.get(
        "/auth/github/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.headers["location"] == f"{FRONT}/login?error=sso_failed"
    assert test_db.scalar(select(Identity)) is None


def test_a_callback_without_a_started_flow_is_refused(web, monkeypatch):
    _github_api(monkeypatch)
    response = web.get("/auth/github/callback?code=abc&state=x", follow_redirects=False)
    assert response.headers["location"] == f"{FRONT}/login?error=sso_failed"


def test_github_without_a_verified_primary_email_gets_no_account(
    web, test_db, monkeypatch
):
    create_user(
        test_db, email="admin@example.com", password="pw12345", role=UserRole.ADMIN
    )
    _github_api(
        monkeypatch,
        emails=[
            {"email": "admin@example.com", "primary": True, "verified": False},
            {"email": "other@example.com", "primary": False, "verified": True},
        ],
    )
    state = _start(web)["state"][0]
    response = web.get(
        f"/auth/github/callback?code=c&state={state}", follow_redirects=False
    )

    assert response.headers["location"] == f"{FRONT}/login?error=no_verified_email"
    assert test_db.scalar(select(Identity)) is None
    assert config.auth_cookie_name not in response.cookies


def test_closed_signup_is_reported_to_the_login_page(web, monkeypatch):
    monkeypatch.setattr(config, "allow_signup", False)
    _github_api(monkeypatch)
    state = _start(web)["state"][0]
    response = web.get(
        f"/auth/github/callback?code=c&state={state}", follow_redirects=False
    )
    assert response.headers["location"] == f"{FRONT}/login?error=signup_closed"


def test_linking_from_settings_adds_github_to_the_signed_in_account(
    web, test_db, monkeypatch
):
    me = create_user(test_db, email="me@example.com", password="pw12345")
    web.cookies.set(config.auth_cookie_name, create_access_token(me))
    _github_api(
        monkeypatch,
        emails=[{"email": "x@example.com", "primary": True, "verified": True}],
    )

    state = _start(web, "/auth/github/link")["state"][0]
    response = web.get(
        f"/auth/github/callback?code=c&state={state}", follow_redirects=False
    )

    assert response.headers["location"] == f"{FRONT}/settings?linked=github"
    assert test_db.scalar(select(Identity)).user_id == me.id


def test_linking_needs_a_session(web):
    assert web.get("/auth/github/link", follow_redirects=False).status_code == 401


def test_unknown_and_unconfigured_providers(web, monkeypatch):
    assert web.get("/auth/facebook/login").status_code == 404
    assert web.get("/auth/infomaniak/login").status_code == 503
    monkeypatch.setattr(config, "github_client_secret", "")
    assert web.get("/auth/github/login").status_code == 503


def test_the_legacy_oidc_routes_still_reach_infomaniak(web, monkeypatch):
    client = MagicMock()
    client.authorize_access_token = AsyncMock(
        return_value={
            "userinfo": {
                "sub": "ik-1",
                "email": "ik@example.com",
                "email_verified": True,
            }
        }
    )
    monkeypatch.setattr(config, "infomaniak_issuer", "https://login.infomaniak.com")
    monkeypatch.setattr(config, "infomaniak_client_id", "cid")
    monkeypatch.setattr(config, "infomaniak_client_secret", "secret")
    monkeypatch.setattr("server.api.auth.get_client", lambda provider: client)

    response = web.get("/auth/oidc/callback?code=c&state=s", follow_redirects=False)

    assert response.headers["location"] == f"{FRONT}/dashboard"
    assert config.auth_cookie_name in response.cookies


def test_sign_out_everywhere_kills_existing_access_tokens(web, test_db):
    me = create_user(test_db, email="me@example.com", password="pw12345")
    old_token = create_access_token(me)
    web.cookies.set(config.auth_cookie_name, old_token)
    assert web.get("/auth/me").status_code == 200

    # Issued in an earlier second than the cut-off.
    import time

    time.sleep(1.05)
    assert web.post("/auth/logout-all", headers={"Origin": FRONT}).status_code == 204

    other = TestClient(web.app, base_url="http://testserver")
    other.cookies.set(config.auth_cookie_name, old_token)
    assert other.get("/auth/me").status_code == 401


def test_a_deactivated_account_is_refused_at_once(web, test_db):
    me = create_user(test_db, email="me@example.com", password="pw12345")
    web.cookies.set(config.auth_cookie_name, create_access_token(me))
    assert web.get("/auth/me").status_code == 200
    me.is_active = False
    test_db.commit()
    assert web.get("/auth/me").status_code == 401
