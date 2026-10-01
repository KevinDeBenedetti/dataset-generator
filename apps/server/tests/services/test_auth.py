"""Tests for JWT issuing/verification and the auth FastAPI dependencies."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from server.core.config import DEV_AUTH_SECRET, config
from server.services.auth import (
    _hash_refresh_token,
    authenticate_user,
    create_access_token,
    decode_access_token,
    ensure_secret_is_safe,
    get_current_user,
    issue_refresh_token,
    purge_expired_refresh_tokens,
    require_admin,
    revoke_refresh_token,
    rotate_refresh_token,
)
from server.services.users import create_user
from server.models.user import RefreshToken, UserRole, AuthProvider


def _request_with(cookies: dict | None = None, headers: dict | None = None) -> Request:
    """Build a minimal Starlette Request carrying cookies/headers."""
    raw_headers = []
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), v.encode()))
    return Request({"type": "http", "headers": raw_headers})


class TestSecretGuard:
    def test_dev_secret_is_refused_outside_development(self, monkeypatch):
        monkeypatch.setattr(config, "auth_secret_key", DEV_AUTH_SECRET)
        monkeypatch.setattr(config, "environment", "production")
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            ensure_secret_is_safe()

    def test_dev_secret_is_allowed_in_development(self, monkeypatch):
        monkeypatch.setattr(config, "auth_secret_key", DEV_AUTH_SECRET)
        monkeypatch.setattr(config, "environment", "development")
        ensure_secret_is_safe()

    def test_real_secret_is_allowed_in_production(self, monkeypatch):
        monkeypatch.setattr(config, "auth_secret_key", "a-real-long-random-secret")
        monkeypatch.setattr(config, "environment", "production")
        ensure_secret_is_safe()


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


class TestRefreshTokens:
    def test_rotate_returns_user_and_new_token(self, test_db):
        user = create_user(test_db, email="r@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)

        rotated = rotate_refresh_token(test_db, raw)
        assert rotated is not None
        rotated_user, new_raw = rotated
        assert rotated_user.id == user.id
        assert new_raw != raw

    def test_rotation_stays_in_the_same_family(self, test_db):
        user = create_user(test_db, email="fam@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        assert rotate_refresh_token(test_db, raw) is not None

        rows = test_db.query(RefreshToken).all()
        assert len(rows) == 2
        assert len({t.family_id for t in rows}) == 1
        # The consumed token is revoked, its successor is live.
        assert sorted(t.revoked_at is None for t in rows) == [False, True]

    def test_unknown_token_is_rejected(self, test_db):
        assert rotate_refresh_token(test_db, "no-such-token") is None

    def test_reuse_revokes_the_whole_family(self, test_db, monkeypatch):
        monkeypatch.setattr(config, "auth_refresh_reuse_grace_seconds", 0)
        user = create_user(test_db, email="steal@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        rotated = rotate_refresh_token(test_db, raw)
        assert rotated is not None
        _, successor = rotated

        # Replaying the consumed token is rejected...
        assert rotate_refresh_token(test_db, raw) is None
        # ...and takes the legitimate successor down with it.
        assert rotate_refresh_token(test_db, successor) is None

    def test_reuse_just_after_rotation_is_a_race_not_theft(self, test_db):
        user = create_user(test_db, email="race@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        first = rotate_refresh_token(test_db, raw)
        second = rotate_refresh_token(test_db, raw)  # same token, within the grace

        assert first is not None and second is not None
        assert first[1] != second[1]
        # Both successors are in the family and both still work.
        assert rotate_refresh_token(test_db, first[1]) is not None
        assert rotate_refresh_token(test_db, second[1]) is not None

    def test_reuse_after_the_grace_is_theft(self, test_db, monkeypatch):
        user = create_user(test_db, email="late@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        assert rotate_refresh_token(test_db, raw) is not None

        # Age the rotation past the grace window.
        row = (
            test_db.query(RefreshToken)
            .filter(RefreshToken.token_hash == _hash_refresh_token(raw))
            .one()
        )
        row.revoked_at = row.revoked_at - timedelta(
            seconds=config.auth_refresh_reuse_grace_seconds + 5
        )
        test_db.commit()
        assert rotate_refresh_token(test_db, raw) is None

    def test_a_logged_out_token_is_never_forgiven(self, test_db):
        """Logout revokes the family *just now* — which must not look like a rotation."""
        user = create_user(test_db, email="out@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        revoke_refresh_token(test_db, raw)
        assert rotate_refresh_token(test_db, raw) is None

    def test_concurrent_rotation_has_a_single_winner(
        self, test_db, test_engine, monkeypatch
    ):
        """Two requests hold the same live token; the conditional UPDATE lets one
        through. (A read-then-write rotation would mint a session for both.)"""
        monkeypatch.setattr(config, "auth_refresh_reuse_grace_seconds", 0)
        user = create_user(test_db, email="cc@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)

        other = sessionmaker(bind=test_engine, expire_on_commit=False)()
        try:
            # The second request has already read the token, still live.
            stale = (
                other.query(RefreshToken)
                .filter(RefreshToken.token_hash == _hash_refresh_token(raw))
                .one()
            )
            assert stale.revoked_at is None

            winner = rotate_refresh_token(test_db, raw)
            assert winner is not None
            # It proceeds on its stale view: the atomic claim finds nothing to claim.
            assert rotate_refresh_token(other, raw) is None
        finally:
            other.close()

    def test_expired_token_is_rejected(self, test_db, monkeypatch):
        user = create_user(test_db, email="old@example.com", password="pw")
        monkeypatch.setattr(config, "auth_refresh_token_ttl_seconds", -10)
        raw = issue_refresh_token(test_db, user)
        assert rotate_refresh_token(test_db, raw) is None

    def test_inactive_user_is_rejected(self, test_db):
        user = create_user(test_db, email="gone@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        user.is_active = False
        test_db.commit()
        assert rotate_refresh_token(test_db, raw) is None

    def test_revoke_kills_the_family(self, test_db):
        user = create_user(test_db, email="bye@example.com", password="pw")
        raw = issue_refresh_token(test_db, user)
        revoke_refresh_token(test_db, raw)
        assert rotate_refresh_token(test_db, raw) is None

    def test_revoke_unknown_token_is_noop(self, test_db):
        revoke_refresh_token(test_db, "never-issued")


class TestPurgeExpiredRefreshTokens:
    def test_deletes_revoked_and_expired_rows(self, test_db, monkeypatch):
        user = create_user(test_db, email="purge@example.com", password="pw")

        # Revoked (via logout).
        revoked_raw = issue_refresh_token(test_db, user)
        revoke_refresh_token(test_db, revoked_raw)

        # Expired but never revoked.
        monkeypatch.setattr(config, "auth_refresh_token_ttl_seconds", -10)
        issue_refresh_token(test_db, user)
        monkeypatch.setattr(config, "auth_refresh_token_ttl_seconds", 1209600)

        # Still live — must survive the purge.
        live_raw = issue_refresh_token(test_db, user)

        deleted = purge_expired_refresh_tokens(test_db)
        assert deleted == 2

        remaining = test_db.query(RefreshToken).all()
        assert len(remaining) == 1
        assert remaining[0].token_hash == _hash_refresh_token(live_raw)

    def test_noop_when_nothing_to_purge(self, test_db):
        user = create_user(test_db, email="clean@example.com", password="pw")
        issue_refresh_token(test_db, user)
        assert purge_expired_refresh_tokens(test_db) == 0
        assert test_db.query(RefreshToken).count() == 1


class TestTokenClaims:
    def _forge(self, **claims):
        import time

        from joserfc import jwt
        from joserfc.jwk import OctKey

        base = {
            "iss": config.auth_issuer,
            "aud": config.auth_audience,
            "sub": "u1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        }
        key = OctKey.import_key(config.auth_secret_key)
        return jwt.encode({"alg": "HS256"}, {**base, **claims}, key)

    def test_issued_tokens_carry_issuer_and_audience(self, test_db):
        user = create_user(test_db, email="iss@example.com", password="pw")
        claims = decode_access_token(create_access_token(user))
        assert claims is not None
        assert claims["iss"] == config.auth_issuer
        assert claims["aud"] == config.auth_audience

    def test_a_correct_hand_forged_token_is_accepted(self):
        assert decode_access_token(self._forge()) is not None

    @pytest.mark.parametrize(
        "claims",
        [
            {"iss": "someone-else"},
            {"aud": "another-service"},
            {"iss": None},
            {"aud": None},
        ],
    )
    def test_wrong_or_missing_issuer_or_audience_is_rejected(self, claims):
        forged = {k: v for k, v in claims.items() if v is not None}
        if any(v is None for v in claims.values()):
            from joserfc import jwt
            from joserfc.jwk import OctKey
            import time

            base = {"sub": "u1", "exp": int(time.time()) + 60}
            base.update(
                {
                    "iss": config.auth_issuer,
                    "aud": config.auth_audience,
                }
            )
            for key, value in claims.items():
                if value is None:
                    base.pop(key)
            token = jwt.encode(
                {"alg": "HS256"}, base, OctKey.import_key(config.auth_secret_key)
            )
        else:
            token = self._forge(**forged)
        assert decode_access_token(token) is None
