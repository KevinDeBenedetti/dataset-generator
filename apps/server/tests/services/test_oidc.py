"""Tests for the OIDC config gating and user upsert logic."""

from server.core.config import config
from server.models.user import UserRole, AuthProvider
from server.services.oidc import is_oidc_configured, upsert_oidc_user
from server.services.users import create_user


class TestIsOidcConfigured:
    def test_false_when_unset(self, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "")
        monkeypatch.setattr(config, "oidc_client_id", "")
        monkeypatch.setattr(config, "oidc_client_secret", "")
        assert is_oidc_configured() is False

    def test_true_when_all_set(self, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "https://login.infomaniak.com")
        monkeypatch.setattr(config, "oidc_client_id", "cid")
        monkeypatch.setattr(config, "oidc_client_secret", "secret")
        assert is_oidc_configured() is True

    def test_false_when_partial(self, monkeypatch):
        monkeypatch.setattr(config, "oidc_issuer", "https://login.infomaniak.com")
        monkeypatch.setattr(config, "oidc_client_id", "")
        monkeypatch.setattr(config, "oidc_client_secret", "secret")
        assert is_oidc_configured() is False


class TestUpsertOidcUser:
    def test_creates_new_account(self, test_db):
        user = upsert_oidc_user(
            test_db, sub="sub-1", email="New@Example.com", email_verified=True
        )
        assert user.provider == AuthProvider.OIDC
        assert user.role == UserRole.USER
        assert user.oidc_sub == "sub-1"
        assert user.email == "new@example.com"
        assert user.hashed_password is None

    def test_returns_existing_by_sub(self, test_db):
        first = upsert_oidc_user(
            test_db, sub="sub-1", email="a@example.com", email_verified=True
        )
        again = upsert_oidc_user(
            test_db, sub="sub-1", email="a@example.com", email_verified=True
        )
        assert again.id == first.id
        assert test_db.query(type(first)).count() == 1

    def test_links_existing_local_account_by_verified_email(self, test_db):
        local = create_user(test_db, email="bob@example.com", password="pw")
        linked = upsert_oidc_user(
            test_db, sub="sub-9", email="bob@example.com", email_verified=True
        )
        assert linked.id == local.id
        assert linked.oidc_sub == "sub-9"
        # Has a local password → stays a local account, just linked.
        assert linked.provider == AuthProvider.LOCAL

    def test_links_passwordless_local_account_flips_provider(self, test_db):
        # An account created without a password (edge case) flips to OIDC.
        passwordless = create_user(
            test_db, email="c@example.com", provider=AuthProvider.LOCAL
        )
        linked = upsert_oidc_user(
            test_db, sub="sub-3", email="c@example.com", email_verified=True
        )
        assert linked.id == passwordless.id
        assert linked.provider == AuthProvider.OIDC

    def test_unverified_email_does_not_link_existing_account(self, test_db):
        """Account-takeover guard: an unverified email must not link to (or hijack)
        an existing local account."""
        admin = create_user(
            test_db, email="admin@example.com", password="pw", role=UserRole.ADMIN
        )

        result = upsert_oidc_user(
            test_db, sub="attacker-sub", email="admin@example.com", email_verified=False
        )

        # A separate account was created, NOT the admin's.
        assert result.id != admin.id
        assert result.oidc_sub == "attacker-sub"
        assert result.email == "attacker-sub@oidc.local"
        assert result.role == UserRole.USER
        # The admin account is untouched (no OIDC sub grafted on).
        test_db.refresh(admin)
        assert admin.oidc_sub is None
        assert admin.role == UserRole.ADMIN

    def test_unverified_email_without_existing_account_uses_placeholder(self, test_db):
        user = upsert_oidc_user(
            test_db, sub="sub-x", email="new@example.com", email_verified=False
        )
        assert user.email == "sub-x@oidc.local"
        assert user.oidc_sub == "sub-x"

    def test_email_verified_defaults_to_unverified(self, test_db):
        """Omitting email_verified is treated as not verified (safe default)."""
        create_user(test_db, email="bob@example.com", password="pw")
        result = upsert_oidc_user(test_db, sub="sub-z", email="bob@example.com")
        assert result.email == "sub-z@oidc.local"

    def test_missing_sub_raises(self, test_db):
        import pytest

        with pytest.raises(ValueError):
            upsert_oidc_user(test_db, sub="", email="x@example.com")
