"""Tests for JWT issuing/verification and the auth FastAPI dependencies."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from server.core.config import config
from server.services.auth import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_current_user,
    require_admin,
)
from server.services.users import create_user
from server.models.user import UserRole, AuthProvider


def _request_with(cookies: dict | None = None, headers: dict | None = None) -> Request:
    """Build a minimal Starlette Request carrying cookies/headers."""
    raw_headers = []
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), v.encode()))
    return Request({"type": "http", "headers": raw_headers})


class TestToken:
    def test_encode_decode_roundtrip(self, test_db):
        user = create_user(test_db, email="t@example.com", password="pw")
        token = create_access_token(user)
        claims = decode_access_token(token)
        assert claims is not None
        assert claims["sub"] == user.id
        assert claims["email"] == "t@example.com"
        assert claims["role"] == UserRole.USER

    def test_decode_invalid_token_returns_none(self):
        assert decode_access_token("not.a.jwt") is None

    def test_decode_expired_token_returns_none(self, test_db, monkeypatch):
        user = create_user(test_db, email="exp@example.com", password="pw")
        # Issue a token that expired one hour ago.
        monkeypatch.setattr(config, "auth_token_ttl_seconds", -3600)
        token = create_access_token(user)
        assert decode_access_token(token) is None


class TestAuthenticateUser:
    def test_success(self, test_db):
        create_user(test_db, email="a@example.com", password="right")
        assert authenticate_user(test_db, "a@example.com", "right") is not None

    def test_wrong_password(self, test_db):
        create_user(test_db, email="a@example.com", password="right")
        assert authenticate_user(test_db, "a@example.com", "wrong") is None

    def test_unknown_email(self, test_db):
        assert authenticate_user(test_db, "nobody@example.com", "x") is None

    def test_oidc_account_without_password_cannot_local_login(self, test_db):
        create_user(
            test_db,
            email="oidc@example.com",
            provider=AuthProvider.OIDC,
            oidc_sub="sub-1",
        )
        assert authenticate_user(test_db, "oidc@example.com", "anything") is None


class TestDependencies:
    def test_get_current_user_from_cookie(self, test_db):
        user = create_user(test_db, email="c@example.com", password="pw")
        token = create_access_token(user)
        request = _request_with(cookies={config.auth_cookie_name: token})
        resolved = get_current_user(request, db=test_db)
        assert resolved.id == user.id

    def test_get_current_user_from_bearer_header(self, test_db):
        user = create_user(test_db, email="b@example.com", password="pw")
        token = create_access_token(user)
        request = _request_with(headers={"Authorization": f"Bearer {token}"})
        assert get_current_user(request, db=test_db).id == user.id

    def test_get_current_user_no_token_raises_401(self, test_db):
        with pytest.raises(HTTPException) as exc:
            get_current_user(_request_with(), db=test_db)
        assert exc.value.status_code == 401

    def test_require_admin_allows_admin(self, test_db):
        admin = create_user(
            test_db, email="admin@example.com", password="pw", role=UserRole.ADMIN
        )
        assert require_admin(admin) is admin

    def test_require_admin_forbids_regular_user(self, test_db):
        user = create_user(test_db, email="u@example.com", password="pw")
        with pytest.raises(HTTPException) as exc:
            require_admin(user)
        assert exc.value.status_code == 403
