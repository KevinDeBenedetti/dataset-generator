"""Handing the pre-multi-user data to a real account (``server.cli claim-legacy``)."""

import pytest
from sqlalchemy import select

from server.cli import main
from server.models.dataset import Dataset
from server.models.job_run import JobRun
from server.models.model_defaults import ModelDefault
from server.models.quality_rules import QualityRules
from server.models.user import SYSTEM_EMAIL, AuthProvider, User
from server.services.legacy import claim_legacy_rows
from server.services.users import create_user


class _Borrowed:
    """The test's session, handed to code that closes its session when done.

    Patching ``test_db.close`` to a no-op instead would leave the session open
    at teardown — its transaction then blocks the schema drop on Postgres (and
    hangs the suite), while SQLite never notices.
    """

    def __init__(self, session):
        self._session = session

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture
def system(test_db):
    user = User(
        id="system-id",
        email=SYSTEM_EMAIL,
        role="user",
        provider=AuthProvider.SYSTEM,
        is_active=False,
    )
    test_db.add(user)
    test_db.commit()
    return user


@pytest.fixture
def kevin(test_db):
    return create_user(test_db, email="kevin@test.local", password="pw12345")


def _legacy_rows(db, system):
    db.add_all(
        [
            Dataset(
                id="d1",
                name="alpha",
                owner_id=system.id,
                qdrant_collection="dataset_alpha",
            ),
            Dataset(
                id="d2",
                name="beta",
                owner_id=system.id,
                qdrant_collection="dataset_beta",
            ),
            JobRun(
                id="r1",
                job_id="github-personal",
                owner_id=system.id,
                status="succeeded",
                options={},
            ),
            ModelDefault(user_id=system.id, role="qa", model_ref="openai:a"),
            ModelDefault(user_id=system.id, role="cleaning", model_ref="openai:c"),
            QualityRules(user_id=system.id, min_answer_words=7),
        ]
    )
    db.commit()


def test_everything_the_system_user_holds_moves_to_the_account(test_db, system, kevin):
    _legacy_rows(test_db, system)

    counts = claim_legacy_rows(test_db, "kevin@test.local")

    assert counts == {
        "datasets": 2,
        "job_runs": 1,
        "model_defaults": 2,
        "quality_rules": 1,
    }
    datasets = test_db.scalars(select(Dataset).order_by(Dataset.name)).all()
    assert [(d.name, d.owner_id) for d in datasets] == [
        ("alpha", kevin.id),
        ("beta", kevin.id),
    ]
    # The Qdrant collection they already use is untouched: nothing to re-embed.
    assert [d.qdrant_collection for d in datasets] == ["dataset_alpha", "dataset_beta"]
    assert test_db.get(JobRun, "r1").owner_id == kevin.id
    assert test_db.get(QualityRules, kevin.id).min_answer_words == 7
    # The placeholder is gone once it holds nothing.
    assert test_db.scalar(select(User).where(User.email == SYSTEM_EMAIL)) is None


def test_a_name_the_account_already_uses_gets_a_legacy_suffix(test_db, system, kevin):
    _legacy_rows(test_db, system)
    test_db.add(Dataset(id="mine", name="alpha", owner_id=kevin.id))
    test_db.commit()

    claim_legacy_rows(test_db, "kevin@test.local")

    names = sorted(
        test_db.scalars(select(Dataset.name).where(Dataset.owner_id == kevin.id))
    )
    assert names == ["alpha", "alpha-legacy", "beta"]
    assert test_db.get(Dataset, "mine").name == "alpha"  # theirs is never renamed


def test_the_accounts_own_settings_win_over_the_legacy_ones(test_db, system, kevin):
    _legacy_rows(test_db, system)
    test_db.add(ModelDefault(user_id=kevin.id, role="qa", model_ref="claude:mine"))
    test_db.add(QualityRules(user_id=kevin.id, min_answer_words=2))
    test_db.commit()

    counts = claim_legacy_rows(test_db, "kevin@test.local")

    assert counts["model_defaults"] == 1  # only "cleaning" moved
    assert test_db.get(ModelDefault, (kevin.id, "qa")).model_ref == "claude:mine"
    assert test_db.get(ModelDefault, (kevin.id, "cleaning")).model_ref == "openai:c"
    assert test_db.get(QualityRules, kevin.id).min_answer_words == 2


def test_unknown_account_and_system_target_are_refused(test_db, system, kevin):
    with pytest.raises(ValueError, match="No account"):
        claim_legacy_rows(test_db, "ghost@test.local")
    with pytest.raises(ValueError, match="cannot claim"):
        claim_legacy_rows(test_db, SYSTEM_EMAIL)


def test_without_a_system_user_there_is_nothing_to_claim(test_db, kevin):
    assert claim_legacy_rows(test_db, "kevin@test.local") == {
        "datasets": 0,
        "job_runs": 0,
        "model_defaults": 0,
        "quality_rules": 0,
    }


def test_the_cli_reports_and_uses_a_nonzero_exit_on_error(
    monkeypatch, test_db, system, kevin, capsys
):
    _legacy_rows(test_db, system)
    monkeypatch.setattr("server.cli.SessionLocal", lambda: _Borrowed(test_db))

    assert main(["claim-legacy", "--email", "kevin@test.local"]) == 0
    assert "2 datasets" in capsys.readouterr().out

    assert main(["claim-legacy", "--email", "ghost@test.local"]) == 1
    assert "No account" in capsys.readouterr().err


def test_gen_key_prints_a_ring_entry_that_parses(capsys):
    from server.core.crypto import parse_ring

    assert main(["gen-key"]) == 0
    entry = capsys.readouterr().out.strip()
    [(key_id, key)] = parse_ring(entry)
    assert key_id.startswith("k") and len(key) == 32


def test_rewrap_secrets_reports_counts(monkeypatch, test_db, capsys):
    monkeypatch.setattr("server.cli.SessionLocal", lambda: _Borrowed(test_db))
    monkeypatch.setattr(
        "server.services.user_secrets.rewrap_all",
        lambda db: {"rewrapped": 2, "unchanged": 1, "failed": 0},
    )

    assert main(["rewrap-secrets"]) == 0
    assert capsys.readouterr().out.strip() == "2 rewrapped, 1 unchanged, 0 failed"

    monkeypatch.setattr(
        "server.services.user_secrets.rewrap_all",
        lambda db: {"rewrapped": 0, "unchanged": 0, "failed": 1},
    )
    assert main(["rewrap-secrets"]) == 1  # a secret nobody could decrypt: non-zero


def test_migrate_applies_the_migrations_to_the_configured_database(monkeypatch, capsys):
    from unittest.mock import patch

    monkeypatch.setattr(
        "server.core.database.SQLALCHEMY_DATABASE_URL",
        "postgresql+psycopg://u:p@db/app",
    )
    with patch("server.migrations.utils.db_utils.upgrade_db") as upgrade:
        assert main(["migrate"]) == 0
    upgrade.assert_called_once_with("postgresql+psycopg://u:p@db/app")
    assert "up to date" in capsys.readouterr().out
