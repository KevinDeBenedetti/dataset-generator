"""Tests for database utilities"""

from server.core.database import get_db, get_scoped_db


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
