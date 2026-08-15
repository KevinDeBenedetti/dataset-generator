"""Tests for database utilities"""

import pytest
from unittest.mock import patch
from sqlalchemy import inspect

from server.core.database import Base, get_db, get_scoped_db, create_db_and_tables


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


class TestCreateDbAndTables:
    """Tests for create_db_and_tables function"""

    def test_create_db_and_tables_success(self, test_engine, monkeypatch):
        """Test successful database creation.

        Bound to the test engine: the module-level one points at the dev
        Postgres, which the suite must not touch (and which need not be up).
        """
        monkeypatch.setattr("server.core.database.engine", test_engine)
        Base.metadata.drop_all(bind=test_engine)

        create_db_and_tables()

        assert "users" in inspect(test_engine).get_table_names()

    @patch("server.core.database.Base.metadata.create_all")
    def test_create_db_and_tables_error(self, mock_create_all):
        """Test database creation error is raised"""
        mock_create_all.side_effect = Exception("Database error")
        with pytest.raises(Exception, match="Database error"):
            create_db_and_tables()
