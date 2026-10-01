"""The account-linking policy: who an SSO sign-in becomes, and who it never becomes."""

import pytest
from sqlalchemy import select

from server.core.config import config
from server.models.dataset import Dataset
from server.models.identity import AuditLog, Identity
from server.models.user import SYSTEM_EMAIL, AuthProvider, User, UserRole
from server.services.identities import (
    LoginRefused,
    is_locked_admin,
    list_identities,
    resolve_login,
    unlink_identity,
)
from server.services.sso import ExternalIdentity
from server.services.users import create_user


def gh(subject="42", email="dev@example.com", verified=True, username="dev"):
    return ExternalIdentity("github", subject, email, verified, username)


def ik(subject="ik-1", email="dev@example.com", verified=True):
    return ExternalIdentity("infomaniak", subject, email, verified)


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    monkeypatch.setattr(config, "allow_signup", True)
    monkeypatch.setattr(config, "admin_emails_raw", "")
    monkeypatch.setattr(config, "allowed_email_domains_raw", "")
    monkeypatch.setattr(config, "sso_trusted_email_providers_raw", "infomaniak,github")


def _actions(db):
    return [
        a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.created_at))
    ]


def test_a_first_sign_in_creates_an_account(test_db):
    user = resolve_login(test_db, gh())

    assert (user.email, user.role, user.provider) == (
        "dev@example.com",
        "user",
        "github",
    )
    assert user.last_login_at is not None
    [identity] = list_identities(test_db, user)
    assert (identity["provider"], identity["username"]) == ("github", "dev")
    assert _actions(test_db) == ["user.signup"]


def test_the_same_identity_signs_in_to_the_same_account(test_db):
    first = resolve_login(test_db, gh())
    # Even after the person changed their GitHub email: the subject is the key.
    again = resolve_login(test_db, gh(email="new@example.com"))
    assert again.id == first.id
    assert test_db.scalar(select(Identity)).email == "new@example.com"


def test_a_verified_email_from_a_trusted_provider_links_the_existing_account(test_db):
    local = create_user(test_db, email="dev@example.com", password="pw12345")

    user = resolve_login(test_db, ik())

    assert user.id == local.id
    assert _actions(test_db) == ["identity.autolinked"]


@pytest.mark.parametrize("make", [gh, ik])
def test_an_unverified_email_never_takes_over_an_account(test_db, make):
    admin = create_user(
        test_db, email="admin@example.com", password="pw12345", role=UserRole.ADMIN
    )
    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, make(email="admin@example.com", verified=False))
    assert refused.value.code == "no_verified_email"
    assert list_identities(test_db, admin) == []
    assert test_db.scalar(select(Identity)) is None


def test_an_untrusted_provider_needs_an_explicit_link(test_db, monkeypatch):
    monkeypatch.setattr(config, "sso_trusted_email_providers_raw", "infomaniak")
    create_user(test_db, email="dev@example.com", password="pw12345")

    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, gh())
    assert refused.value.code == "link_required"


def test_linking_from_a_session_adds_the_identity_to_that_account(test_db):
    me = create_user(test_db, email="me@example.com", password="pw12345")

    user = resolve_login(test_db, gh(email="other@example.com"), link_to=me)

    assert user.id == me.id
    assert [i["provider"] for i in list_identities(test_db, me)] == ["github"]
    assert "identity.linked" in _actions(test_db)


def test_an_identity_of_someone_else_cannot_be_linked(test_db):
    owner = resolve_login(test_db, gh())
    me = create_user(test_db, email="me@example.com", password="pw12345")

    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, gh(), link_to=me)
    assert refused.value.code == "identity_in_use"
    assert [i["provider"] for i in list_identities(test_db, owner)] == ["github"]
    assert list_identities(test_db, me) == []


def test_sign_up_can_be_closed_and_limited_to_domains(test_db, monkeypatch):
    monkeypatch.setattr(config, "allow_signup", False)
    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, gh())
    assert refused.value.code == "signup_closed"

    monkeypatch.setattr(config, "allow_signup", True)
    monkeypatch.setattr(
        config, "allowed_email_domains_raw", "@corp.example, lab.example"
    )
    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, gh(email="dev@gmail.com"))
    assert refused.value.code == "domain_not_allowed"
    assert (
        resolve_login(test_db, gh(email="dev@corp.example")).email == "dev@corp.example"
    )


def test_admin_emails_are_promoted_and_may_always_sign_up(test_db, monkeypatch):
    monkeypatch.setattr(config, "allow_signup", False)
    monkeypatch.setattr(config, "admin_emails_raw", "Boss@Example.com")

    boss = resolve_login(test_db, gh(email="boss@example.com"))

    assert boss.role == UserRole.ADMIN
    assert is_locked_admin(boss)
    assert _actions(test_db) == ["user.signup", "user.promoted"]


def test_an_admin_email_receives_the_parked_legacy_data_once(test_db, monkeypatch):
    system = User(
        id="sys",
        email=SYSTEM_EMAIL,
        role="user",
        provider=AuthProvider.SYSTEM,
        is_active=False,
    )
    test_db.add(system)
    # The models declare no relationships, so the session doesn't know the user
    # must be inserted before its dataset: Postgres enforces the foreign key.
    test_db.commit()
    test_db.add(Dataset(id="d1", name="old", owner_id="sys"))
    test_db.commit()
    monkeypatch.setattr(config, "admin_emails_raw", "boss@example.com")

    boss = resolve_login(test_db, gh(email="boss@example.com"))

    assert test_db.get(Dataset, "d1").owner_id == boss.id
    assert test_db.get(User, "sys") is None
    assert "legacy.claimed" in _actions(test_db)


def test_a_disabled_account_cannot_sign_in(test_db):
    user = resolve_login(test_db, gh())
    user.is_active = False
    test_db.commit()

    with pytest.raises(LoginRefused) as refused:
        resolve_login(test_db, gh())
    assert refused.value.code == "account_disabled"


def test_the_reserved_system_address_is_never_linked(test_db):
    test_db.add(User(id="sys", email=SYSTEM_EMAIL, role="user", is_active=False))
    test_db.commit()
    with pytest.raises(LoginRefused):
        resolve_login(test_db, gh(email=SYSTEM_EMAIL))


def test_the_last_way_to_sign_in_cannot_be_unlinked(test_db, monkeypatch):
    user = resolve_login(test_db, gh())
    [only] = list_identities(test_db, user)
    with pytest.raises(LookupError):
        unlink_identity(test_db, user, only["id"])

    resolve_login(test_db, ik(email="dev@example.com"), link_to=user)
    unlink_identity(test_db, user, only["id"])
    assert [i["provider"] for i in list_identities(test_db, user)] == ["infomaniak"]
    assert "identity.unlinked" in _actions(test_db)


def test_a_password_counts_as_a_way_in_only_when_local_login_is_on(
    test_db, monkeypatch
):
    user = create_user(test_db, email="dev@example.com", password="pw12345")
    resolve_login(test_db, gh(), link_to=user)
    [identity] = list_identities(test_db, user)

    monkeypatch.setattr(config, "enable_local_login", False)
    with pytest.raises(LookupError):
        unlink_identity(test_db, user, identity["id"])
    monkeypatch.setattr(config, "enable_local_login", True)
    unlink_identity(test_db, user, identity["id"])


def test_someone_elses_identity_cannot_be_unlinked(test_db):
    owner = resolve_login(test_db, gh())
    [identity] = list_identities(test_db, owner)
    me = create_user(test_db, email="me@example.com", password="pw12345")
    with pytest.raises(ValueError):
        unlink_identity(test_db, me, identity["id"])
