"""Signing users in with their Hugging Face token (auth/hf_token.py).

The ``whoami`` answers are in tests/fixtures/hf_whoami. They follow the Hub's
documented shape and are written by hand: replace them with recorded answers
(a write, a read and a fine-grained token) when one is at hand.
"""

import json
import logging
from pathlib import Path

import pytest

from server.auth import hf_token
from server.models.identity import AuditLog
from server.models.user import AuthProvider, User
from server.services import user_secrets
from server.services.credentials import HF_TOKEN

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "hf_whoami"
TOKEN = "hf_" + "a" * 34
OTHER_TOKEN = "hf_" + "b" * 34


def whoami(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def hub(monkeypatch):
    """The Hub's answer per token: set ``hub[token] = whoami(...)``; an unknown
    token is one the Hub rejects."""
    answers: dict = {}

    def fetch(token: str) -> dict:
        if token not in answers:
            raise hf_token.SignInRefused(
                "token_invalid", "Hugging Face rejected this token"
            )
        answer = answers[token]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(hf_token, "whoami_fetcher", fetch)
    return answers


def open_signup(_info):
    return None


class TestTokenInfo:
    def test_write_token(self):
        info = hf_token.token_info(whoami("write"))
        assert info.can_write and info.role == "write"
        assert info.hf_id == "64f1c0ffee0000000000aaaa"
        assert info.orgs == ["open-data-lab"]

    def test_read_token(self):
        info = hf_token.token_info(whoami("read"))
        assert not info.can_write and info.role == "read"

    def test_fine_grained_token_writes_where_it_is_scoped(self):
        info = hf_token.token_info(whoami("fine_grained"))
        assert info.can_write and info.role == "fineGrained"
        assert info.orgs_without_write == ["other-org"]

    def test_fine_grained_token_without_repo_write(self):
        assert not hf_token.token_info(whoami("fine_grained_read_only")).can_write


class TestShape:
    @pytest.mark.parametrize(
        "token",
        ["", "sk-abc", "hf_short", "hf_" + "a" * 300, "hf_ aaaaaaaaaaaaaaaaaaaaaa"],
    )
    def test_malformed_tokens_never_reach_the_hub(self, hub, token):
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.check_token("alice", token)
        assert exc.value.code == "token_malformed"


class TestCheck:
    def test_a_write_token_of_that_user_passes(self, hub):
        hub[TOKEN] = whoami("write")
        assert hf_token.check_token("Alice", TOKEN).username == "alice"

    def test_another_users_token_is_refused(self, hub):
        hub[TOKEN] = whoami("write")
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.check_token("bob", TOKEN)
        assert exc.value.code == "token_other_account"

    @pytest.mark.parametrize("fixture", ["read", "fine_grained_read_only"])
    def test_a_token_that_cannot_write_is_refused(self, hub, fixture):
        hub[TOKEN] = whoami(fixture)
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.check_token("alice", TOKEN)
        assert exc.value.code == "token_read_only" and exc.value.status == 403

    def test_a_revoked_token_is_refused(self, hub):
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.check_token("alice", TOKEN)
        assert exc.value.code == "token_invalid"

    def test_a_hub_outage_is_not_a_refusal(self, hub):
        hub[TOKEN] = hf_token.HubUnavailable()
        with pytest.raises(hf_token.HubUnavailable):
            hf_token.check_token("alice", TOKEN)


class TestSignIn:
    def test_the_first_sign_in_creates_the_account(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("write")
        user = hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        assert user.hf_id == "64f1c0ffee0000000000aaaa"
        assert user.provider == AuthProvider.HF
        assert user.hf_username == "alice" and user.email == "alice@example.com"
        assert user_secrets.load_credentials(user.id).secret(HF_TOKEN) == TOKEN
        assert user_secrets.get_settings(user.id)["hf_namespace"] == "alice"
        assert [a.action for a in test_db.query(AuditLog)] == ["user.signup.hf"]

    def test_the_account_is_found_again_after_a_rename(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("write")
        first = hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        renamed = {**whoami("write"), "name": "alice-renamed"}
        hub[OTHER_TOKEN] = renamed
        again = hf_token.sign_in(
            test_db, "alice-renamed", OTHER_TOKEN, signup_check=open_signup
        )
        assert again.id == first.id and again.hf_username == "alice-renamed"
        assert test_db.query(User).count() == 1
        # A different token replaces the stored one: how a user rotates it.
        assert user_secrets.load_credentials(again.id).secret(HF_TOKEN) == OTHER_TOKEN

    def test_the_sign_up_policy_can_refuse_a_new_account(
        self, hub, test_db, datasets_db
    ):
        hub[TOKEN] = whoami("write")
        refusal = hf_token.SignInRefused("signup_closed", "closed", 403)
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.sign_in(test_db, "alice", TOKEN, signup_check=lambda _i: refusal)
        assert exc.value.code == "signup_closed"
        assert test_db.query(User).count() == 0

    def test_an_existing_account_is_not_re_checked(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("write")
        hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        refusal = hf_token.SignInRefused("signup_closed", "closed", 403)
        hf_token.sign_in(test_db, "alice", TOKEN, signup_check=lambda _i: refusal)

    def test_a_disabled_account_is_refused(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("write")
        user = hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        user.is_active = False
        test_db.commit()
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        assert exc.value.code == "account_disabled"

    def test_an_email_another_account_holds_is_not_taken(
        self, hub, test_db, datasets_db
    ):
        from server.services.users import create_user

        create_user(test_db, email="alice@example.com", password="pw12345")
        hub[TOKEN] = whoami("write")
        user = hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        assert user.email is None  # never joined by email
        assert test_db.query(User).count() == 2

    def test_an_unverified_email_is_not_kept(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("fine_grained")
        user = hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
        assert user.email is None

    def test_the_token_never_reaches_the_logs_or_the_audit(
        self, hub, test_db, datasets_db, caplog
    ):
        hub[TOKEN] = whoami("write")
        with caplog.at_level(logging.DEBUG):
            hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)
            with pytest.raises(hf_token.SignInRefused):
                hf_token.sign_in(test_db, "bob", TOKEN, signup_check=open_signup)
        assert TOKEN not in caplog.text
        entries = repr([(a.detail, a.actor_label) for a in test_db.query(AuditLog)])
        assert TOKEN not in entries


def test_hf_tokens_are_redacted():
    from server.core.redact import redact

    assert TOKEN not in redact(f"token={TOKEN}")


class TestSignupPolicy:
    """The default sign-up check is the backoffice policy (services/platform.py)."""

    def test_orgs_policy_takes_a_member(self, hub, test_db, datasets_db, monkeypatch):
        from server.services import platform

        values = {
            "signup_policy": "orgs",
            "signup_orgs": ["open-data-lab"],
            "signup_usernames": [],
        }
        monkeypatch.setattr(platform, "get", lambda key: values[key])
        hub[TOKEN] = whoami("write")  # alice is in open-data-lab
        assert hf_token.sign_in(test_db, "alice", TOKEN).hf_username == "alice"

    def test_closed_policy_refuses_with_403(
        self, hub, test_db, datasets_db, monkeypatch
    ):
        from server.services import platform

        monkeypatch.setattr(platform, "signup_policy", lambda: "closed")
        monkeypatch.setattr(
            platform, "get", lambda key: [] if key == "signup_usernames" else None
        )
        hub[TOKEN] = whoami("write")
        with pytest.raises(hf_token.SignInRefused) as exc:
            hf_token.sign_in(test_db, "alice", TOKEN)
        assert exc.value.code == "signup_closed" and exc.value.status == 403


class TestRecheck:
    """Stored tokens are re-checked before a publication and once a day."""

    @pytest.fixture
    def alice(self, hub, test_db, datasets_db):
        hub[TOKEN] = whoami("write")
        return hf_token.sign_in(test_db, "alice", TOKEN, signup_check=open_signup)

    def _status(self, user_id):
        return user_secrets.secret_statuses(user_id)[HF_TOKEN]

    def test_a_sign_in_records_a_good_check(self, alice):
        status = self._status(alice.id)
        assert status["last_state"] == "ok" and status["last_checked_at"]

    def test_a_revoked_token_ends_the_sessions(self, alice, hub, test_db):
        del hub[TOKEN]
        hf_token.clear_check_cache()
        assert hf_token.check_stored_token(alice.id) == "revoked"
        test_db.refresh(alice)
        assert alice.sessions_valid_after is not None
        assert self._status(alice.id)["last_state"] == "revoked"
        actions = [a.action for a in test_db.query(AuditLog)]
        assert actions.count("user.hf_token_invalid") == 1
        # Checked again: no second audit entry, sessions not bumped again.
        hf_token.clear_check_cache()
        hf_token.check_stored_token(alice.id)
        actions = [a.action for a in test_db.query(AuditLog)]
        assert actions.count("user.hf_token_invalid") == 1

    def test_a_hub_outage_changes_nothing(self, alice, hub, test_db):
        hub[TOKEN] = hf_token.HubUnavailable()
        hf_token.clear_check_cache()
        assert hf_token.check_stored_token(alice.id) == "hub_unavailable"
        test_db.refresh(alice)
        assert alice.sessions_valid_after is None
        assert self._status(alice.id)["last_state"] == "ok"

    def test_a_downgraded_token_refuses_a_publication(self, alice, hub):
        from server.services.credentials import resolve_credentials

        hub[TOKEN] = whoami("read")
        hf_token.clear_check_cache()
        with pytest.raises(hf_token.TokenUnusable) as exc:
            hf_token.ensure_can_publish(resolve_credentials(alice.id))
        assert "can no longer write" in str(exc.value)
        assert self._status(alice.id)["last_state"] == "read_only"

    def test_checks_are_cached_for_ten_minutes(self, hub, monkeypatch):
        calls = []
        answer = whoami("write")

        def counted(token):
            calls.append(token)
            return answer

        monkeypatch.setattr(hf_token, "whoami_fetcher", counted)
        hf_token.clear_check_cache()
        assert hf_token.token_state(TOKEN) == "ok"
        assert hf_token.token_state(TOKEN) == "ok"
        assert len(calls) == 1

    def test_the_sweep_checks_the_oldest_unchecked_tokens(
        self, alice, hub, test_db, monkeypatch
    ):
        from datetime import datetime, timedelta, timezone

        from server.models.user_secret import UserSecret

        row = test_db.get(UserSecret, {"user_id": alice.id, "kind": HF_TOKEN})
        row.last_checked_at = datetime.now(timezone.utc) - timedelta(days=2)
        test_db.commit()
        del hub[TOKEN]
        hf_token.clear_check_cache()
        assert hf_token.recheck_stale_tokens() == 1
        assert self._status(alice.id)["last_state"] == "revoked"
        # Checked just now: the next sweep leaves it alone.
        assert hf_token.recheck_stale_tokens() == 0

    def test_a_new_token_clears_the_bad_state(self, alice, hub, test_db):
        del hub[TOKEN]
        hf_token.clear_check_cache()
        hf_token.check_stored_token(alice.id)
        hub[OTHER_TOKEN] = whoami("write")
        hf_token.sign_in(test_db, "alice", OTHER_TOKEN, signup_check=open_signup)
        assert self._status(alice.id)["last_state"] == "ok"
