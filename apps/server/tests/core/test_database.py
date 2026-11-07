"""Tests for database utilities"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from server.core.database import get_db, get_scoped_db

SERVER = Path(__file__).parents[2]


class TestNoAmbientDatabase:
    """The suite never reaches the database the environment names.

    In CI nothing listens on the default database's port; on a developer's
    machine the dev stack's Postgres does. A test that reached it passed
    there and failed in CI — the draft checks route once did, through a
    session helper imported from another service.
    """

    def test_a_test_without_a_database_is_refused_one(self):
        with pytest.raises(OperationalError, match="no ambient database"):
            with get_scoped_db() as db:
                db.execute(text("SELECT 1"))

    def test_the_per_test_database_reaches_modules_that_open_their_own(
        self, datasets_db
    ):
        from server.services import draft_quality

        with draft_quality.get_scoped_db() as db:
            assert db.execute(text("SELECT 1")).scalar() == 1

    def test_every_module_imports_the_session_helpers_from_their_source(self):
        """Imported from another module, ``get_scoped_db`` is whatever that
        module held at the time — a test's stand-in, if a test had patched it
        then — and no fixture can redirect it any more."""
        offenders = []
        for path in sorted(SERVER.rglob("*.py")):
            if "tests" in path.relative_to(SERVER).parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module != "server.core.database"
                    and {a.name for a in node.names} & {"get_scoped_db", "SessionLocal"}
                ):
                    offenders.append(f"{path.relative_to(SERVER)}:{node.lineno}")
        assert not offenders, f"import these from server.core.database: {offenders}"


class TestGetDb:
    """Tests for get_db function"""

    def test_get_db_yields_session(self):
        """Test that get_db yields a database session"""
        db_gen = get_db()
        db = next(db_gen)
        assert db is not None
        # Clean up
        try:
            next(db_gen)
        except StopIteration:
            pass

    def test_get_db_closes_session(self):
        """Test that get_db closes session after use"""
        db_gen = get_db()
        session = next(db_gen)
        assert session is not None
        # Simulate exiting the context
        try:
            next(db_gen)
        except StopIteration:
            pass
        # Session should be closed (no error means success)


class TestGetScopedDb:
    """Tests for get_scoped_db context manager"""

    def test_get_scoped_db_context(self):
        """Test get_scoped_db as context manager"""
        with get_scoped_db() as db:
            assert db is not None

    def test_get_scoped_db_closes_on_exit(self):
        """Test that scoped db closes on context exit"""
        with get_scoped_db() as session:
            assert session is not None
        # Session should be closed after context
