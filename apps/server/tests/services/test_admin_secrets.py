"""The admin signed in from the deployment's secrets (auth/admin_secrets.py)."""

import pytest

from server.auth import admin_secrets
from server.core.config import config
from server.models.identity import AuditLog
from server.models.user import AuthProvider, User, UserRole
from server.services.credentials import Credentials, resolve_credentials

PASSWORD = "correct horse battery staple"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DP"
# RFC 6238's test time: 1970-01-01T00:00:59Z sits in step 1.
NOW = 1_700_000_000.0


@pytest.fixture(scope="module")
def password_hash() -> str:
    return admin_secrets.hash_password(PASSWORD)


@pytest.fixture
def admin_env(monkeypatch, password_hash):
    monkeypatch.setattr(config, "admin_username", "operator")
    monkeypatch.setattr(config, "admin_password_hash", password_hash)
    monkeypatch.setattr(config, "admin_password", "")
    monkeypatch.setattr(config, "admin_totp_secret", "")


def _admin(db) -> User:
    admin = admin_secrets.ensure_admin_account(db)
    assert admin is not None
    return admin


class TestHash:
    def test_the_hash_is_argon2id(self):
        assert admin_secrets.hash_password("x" * 12).startswith("$argon2id$")


class TestVerify:
    def test_the_right_values_pass(self, admin_env):
        assert admin_secrets.verify_admin("operator", PASSWORD)

    def test_the_username_is_case_insensitive(self, admin_env):
        assert admin_secrets.verify_admin("Operator", PASSWORD)

    @pytest.mark.parametrize(
        "username,password", [("operator", "wrong"), ("someone", PASSWORD), ("", "")]
    )
    def test_a_wrong_value_fails(self, admin_env, username, password):
        assert not admin_secrets.verify_admin(username, password)

    def test_nothing_passes_without_secrets(self, monkeypatch):
        monkeypatch.setattr(config, "admin_username", "")
        monkeypatch.setattr(config, "admin_password_hash", "")
        assert not admin_secrets.configured()
        assert not admin_secrets.verify_admin("", "")

    def test_a_password_in_clear_only_works_in_development(self, monkeypatch):
        monkeypatch.setattr(config, "admin_username", "operator")
        monkeypatch.setattr(config, "admin_password_hash", "")
        monkeypatch.setattr(config, "admin_password", "devpass")
        monkeypatch.setattr(config, "environment", "development")
        assert admin_secrets.verify_admin("operator", "devpass")
        monkeypatch.setattr(config, "environment", "production")
        assert not admin_secrets.configured()
        assert not admin_secrets.verify_admin("operator", "devpass")


class TestTotp:
    def test_rfc_6238_vector(self):
        # RFC 6238, appendix B: SHA-1, T=59 → 94287082 (8 digits; 6 = 287082).
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # gitleaks:allow — RFC 6238 test key "12345678901234567890"
        assert admin_secrets.totp_code(secret, 59) == "287082"

    @pytest.fixture
    def with_totp(self, admin_env, monkeypatch):
        monkeypatch.setattr(config, "admin_totp_secret", TOTP_SECRET)

    def test_the_current_code_passes(self, with_totp):
        code = admin_secrets.totp_code(TOTP_SECRET, NOW)
        assert admin_secrets.verify_admin("operator", PASSWORD, code, now=NOW)

    @pytest.mark.parametrize("offset", [-1, 1])
    def test_one_step_of_drift_passes(self, with_totp, offset):
        code = admin_secrets.totp_code(TOTP_SECRET, NOW, step_offset=offset)
        assert admin_secrets.verify_admin("operator", PASSWORD, code, now=NOW)

    @pytest.mark.parametrize("offset", [-2, 2])
    def test_two_steps_fail(self, with_totp, offset):
        code = admin_secrets.totp_code(TOTP_SECRET, NOW, step_offset=offset)
        assert not admin_secrets.verify_admin("operator", PASSWORD, code, now=NOW)

    @pytest.mark.parametrize("otp", [None, "", "12345", "abcdef"])
    def test_a_missing_or_malformed_code_fails(self, with_totp, otp):
        assert not admin_secrets.verify_admin("operator", PASSWORD, otp, now=NOW)

    def test_a_good_code_does_not_save_a_wrong_password(self, with_totp):
        code = admin_secrets.totp_code(TOTP_SECRET, NOW)
        assert not admin_secrets.verify_admin("operator", "wrong", code, now=NOW)


class TestEnsureAccount:
    def test_creates_the_admin_once(self, admin_env, test_db):
        first = admin_secrets.ensure_admin_account(test_db)
        again = admin_secrets.ensure_admin_account(test_db)
        assert first is not None and again is not None and first.id == again.id
        assert first.role == UserRole.ADMIN
        assert first.provider == AuthProvider.SECRETS
        assert first.hashed_password is None
        assert test_db.query(User).count() == 1
        actions = [a.action for a in test_db.query(AuditLog)]
        assert actions == ["admin.created"]

    def test_restores_a_demoted_or_disabled_admin(self, admin_env, test_db):
        admin = _admin(test_db)
        admin.role = UserRole.USER
        admin.is_active = False
        test_db.commit()
        again = _admin(test_db)
        assert again.role == UserRole.ADMIN and again.is_active

    def test_a_renamed_username_disables_the_previous_admin(
        self, admin_env, test_db, monkeypatch
    ):
        old = _admin(test_db)
        monkeypatch.setattr(config, "admin_username", "new-operator")
        new = _admin(test_db)
        test_db.refresh(old)
        assert new.id != old.id and new.is_active
        assert not old.is_active
        assert old.sessions_valid_after is not None
        disabled = test_db.query(AuditLog).filter_by(action="admin.disabled").one()
        assert disabled.target_user_id == old.id

    def test_nothing_without_secrets(self, monkeypatch, test_db):
        monkeypatch.setattr(config, "admin_username", "")
        assert admin_secrets.ensure_admin_account(test_db) is None
        assert test_db.query(User).count() == 0


class TestCredentials:
    def test_the_admin_acts_with_the_servers_keys(
        self, admin_env, test_db, datasets_db, monkeypatch
    ):
        monkeypatch.setattr(config, "allow_env_credentials", False)
        monkeypatch.setenv("ADMIN_HF_TOKEN", "hf_admin_token")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
        admin = _admin(test_db)
        creds = resolve_credentials(admin.id)
        assert creds.secret("hf_token") == "hf_admin_token"
        assert creds.secret("openai_api_key") == "sk-server"
        assert creds.user_id == admin.id

    def test_hf_token_is_the_fallback_of_admin_hf_token(self, monkeypatch):
        monkeypatch.delenv("ADMIN_HF_TOKEN", raising=False)
        monkeypatch.setenv("HF_TOKEN", "hf_plain")
        assert Credentials.from_env().secret("hf_token") == "hf_plain"


class TestCli:
    def test_hash_password_prints_a_hash_that_verifies(self, monkeypatch, capsys):
        from argon2 import PasswordHasher

        from server import cli

        monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)
        assert cli.main(["hash-password"]) == 0
        printed = capsys.readouterr().out.strip()
        assert printed.startswith("$argon2id$")
        assert PasswordHasher().verify(printed, PASSWORD)

    def test_hash_password_refuses_a_short_or_mistyped_one(self, monkeypatch):
        from server import cli

        monkeypatch.setattr("getpass.getpass", lambda prompt="": "short")
        assert cli.main(["hash-password"]) == 1
        answers = iter([PASSWORD, PASSWORD + "!"])
        monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
        assert cli.main(["hash-password"]) == 1

    def test_promote_admin_is_gone(self):
        from server import cli

        with pytest.raises(SystemExit):
            cli.main(["promote-admin", "someone@example.com"])
