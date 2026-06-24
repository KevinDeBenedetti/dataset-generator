"""Tests for password hashing, the user service, and dev seeding."""

from server.core.security import hash_password, verify_password
from server.models.user import User, UserRole, AuthProvider
from server.services.users import (
    create_user,
    get_user_by_email,
    seed_dev_users,
)


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        hashed = hash_password("s3cret-pw")
        assert hashed != "s3cret-pw"  # never store plaintext
        assert verify_password("s3cret-pw", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_empty_or_missing_hash_is_rejected(self):
        # OIDC-only accounts have no local password.
        assert verify_password("anything", "") is False
        assert verify_password("anything", "not-a-bcrypt-hash") is False

    def test_long_password_over_72_bytes(self):
        # Bcrypt caps at 72 bytes; hashing/verifying must still work.
        pw = "a" * 200
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True


class TestUserService:
    def test_create_user_normalizes_email_and_hashes_password(self, test_db):
        user = create_user(test_db, email="Alice@Example.com", password="pw12345")
        assert user.email == "alice@example.com"
        assert user.role == UserRole.USER
        assert user.provider == AuthProvider.LOCAL
        assert user.hashed_password and user.hashed_password != "pw12345"
        assert verify_password("pw12345", user.hashed_password) is True

    def test_get_user_by_email_is_case_insensitive(self, test_db):
        create_user(test_db, email="bob@example.com", password="pw")
        assert get_user_by_email(test_db, "BOB@example.com") is not None

    def test_create_oidc_user_without_password(self, test_db):
        user = create_user(
            test_db,
            email="oidc@example.com",
            role=UserRole.USER,
            provider=AuthProvider.OIDC,
            oidc_sub="sub-123",
        )
        assert user.hashed_password is None
        assert user.oidc_sub == "sub-123"

    def test_create_user_rejects_unknown_role(self, test_db):
        import pytest

        with pytest.raises(ValueError):
            create_user(test_db, email="x@example.com", password="pw", role="root")

    def test_admin_flag(self, test_db):
        admin = create_user(
            test_db, email="a@example.com", password="pw", role=UserRole.ADMIN
        )
        assert admin.is_admin is True


class TestSeedDevUsers:
    def test_seeds_two_users(self, test_db):
        created = seed_dev_users(test_db)
        assert created == 2
        users = test_db.query(User).all()
        roles = {u.email: u.role for u in users}
        assert roles == {
            "admin@example.com": UserRole.ADMIN,
            "user@example.com": UserRole.USER,
        }

    def test_is_idempotent(self, test_db):
        assert seed_dev_users(test_db) == 2
        # Running again creates nothing and doesn't duplicate.
        assert seed_dev_users(test_db) == 0
        assert test_db.query(User).count() == 2

    def test_seeded_passwords_match_defaults(self, test_db):
        seed_dev_users(test_db)
        admin = get_user_by_email(test_db, "admin@example.com")
        user = get_user_by_email(test_db, "user@example.com")
        assert admin is not None and admin.hashed_password is not None
        assert user is not None and user.hashed_password is not None
        assert verify_password("admin1234", admin.hashed_password) is True
        assert verify_password("user1234", user.hashed_password) is True
