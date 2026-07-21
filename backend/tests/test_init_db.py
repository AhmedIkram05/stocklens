"""
Tests for database initialisation / Alembic migration orchestration.

Reuses the same test-DB transaction isolation from conftest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestNormaliseDSN:
    """_normalise_dsn strips the +asyncpg driver suffix."""

    def test_strips_asyncpg(self):
        from src.database.init_db import _normalise_dsn

        result = _normalise_dsn("postgresql+asyncpg://user:pass@localhost/db")
        assert result == "postgresql://user:pass@localhost/db"

    def test_preserves_plain_postgresql(self):
        from src.database.init_db import _normalise_dsn

        result = _normalise_dsn("postgresql://user:pass@localhost/db")
        assert result == "postgresql://user:pass@localhost/db"

    def test_only_replaces_first_occurrence(self):
        from src.database.init_db import _normalise_dsn

        result = _normalise_dsn("postgresql+asyncpg://host1/db?url=postgresql+asyncpg://host2")
        assert result == "postgresql://host1/db?url=postgresql+asyncpg://host2"


class TestDetectAndFixBrokenState:
    """_detect_and_fix_broken_state — migration health check."""

    @patch("src.database.init_db.asyncpg.connect")
    async def test_skips_when_version_not_bridge(self, mock_connect: AsyncMock):
        """When alembic_version is not d2f4e1b3c5a7, no fix is applied."""
        from src.database.init_db import _detect_and_fix_broken_state

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = "0010"  # clean state
        mock_connect.return_value = mock_conn

        await _detect_and_fix_broken_state()

        mock_conn.fetchval.assert_called_once_with("SELECT version_num FROM alembic_version")
        # _FIX_SQL should not have been executed
        assert mock_conn.execute.call_count == 0
        mock_conn.close.assert_called_once()

    @patch("src.database.init_db.asyncpg.connect")
    async def test_skips_when_users_table_exists(self, mock_connect: AsyncMock):
        """Bridge version but users table exists → no fix needed."""
        from src.database.init_db import _detect_and_fix_broken_state

        mock_conn = AsyncMock()
        # First query returns bridge version
        mock_conn.fetchval.return_value = "d2f4e1b3c5a7"
        # Second query: users table exists
        mock_conn.fetchval.side_effect = ["d2f4e1b3c5a7", True]

        mock_connect.return_value = mock_conn

        await _detect_and_fix_broken_state()

        # Should check users table existence
        calls = [c for c in mock_conn.fetchval.call_args_list if "information_schema" in str(c)]
        assert len(calls) == 1
        # _FIX_SQL should not run
        assert mock_conn.execute.call_count == 0
        mock_conn.close.assert_called_once()

    @patch("src.database.init_db.asyncpg.connect")
    async def test_applies_fix_when_bridge_and_no_users(self, mock_connect: AsyncMock):
        """Bridge version + missing users table → fix is applied."""
        from src.database.init_db import _detect_and_fix_broken_state

        mock_conn = AsyncMock()
        mock_conn.fetchval.side_effect = ["d2f4e1b3c5a7", False]  # bridge, no users

        mock_connect.return_value = mock_conn

        await _detect_and_fix_broken_state()

        # Should execute _FIX_SQL and update alembic_version
        execute_calls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("CREATE TABLE IF NOT EXISTS users" in str(c) for c in execute_calls)
        assert any(
            "UPDATE alembic_version SET version_num = '0010'" in str(c) for c in execute_calls
        )
        mock_conn.close.assert_called_once()

    @patch("src.database.init_db.asyncpg.connect")
    async def test_handles_missing_alembic_version_table(self, mock_connect: AsyncMock):
        """When alembic_version table doesn't exist, fetchval returns None."""
        from src.database.init_db import _detect_and_fix_broken_state

        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = None  # no alembic_version row
        mock_connect.return_value = mock_conn

        await _detect_and_fix_broken_state()

        # Should skip — no bridge version detected
        assert mock_conn.execute.call_count == 0
        mock_conn.close.assert_called_once()

    @patch("src.database.init_db.asyncpg.connect")
    async def test_handles_undefined_table_error(self, mock_connect: AsyncMock):
        """UndefinedTableError (table doesn't exist yet) is caught and skipped."""
        import asyncpg

        from src.database.init_db import _detect_and_fix_broken_state

        mock_conn = AsyncMock()
        mock_conn.fetchval.side_effect = asyncpg.exceptions.UndefinedTableError(
            'relation "alembic_version" does not exist'
        )
        mock_connect.return_value = mock_conn

        await _detect_and_fix_broken_state()

        # Should skip without crashing
        mock_conn.close.assert_called_once()


class TestRunMigrations:
    """run_migrations — Alembic migration orchestration."""

    @patch("src.database.init_db._detect_and_fix_broken_state", new_callable=AsyncMock)
    @patch("src.database.init_db.asyncio.to_thread")
    async def test_runs_upgrade_and_fix(self, mock_to_thread, mock_fix):
        """run_migrations calls upgrade then _detect_and_fix_broken_state."""
        from src.database.init_db import run_migrations

        await run_migrations()

        mock_to_thread.assert_called_once()
        # Verify the first arg to to_thread is alembic.command.upgrade
        args, _ = mock_to_thread.call_args
        assert args[0].__name__ == "upgrade"
        mock_fix.assert_awaited_once()

    @patch("src.database.init_db._detect_and_fix_broken_state", new_callable=AsyncMock)
    @patch("src.database.init_db.asyncio.to_thread")
    async def test_handles_programming_error_gracefully(self, mock_to_thread, mock_fix):
        """ProgrammingError from alembic is caught and logged."""
        from sqlalchemy.exc import ProgrammingError

        class DummyOrig(Exception):
            pass

        mock_to_thread.side_effect = ProgrammingError("statement", {}, DummyOrig("already applied"))

        from src.database.init_db import run_migrations

        await run_migrations()

        # Should still run the fix even if upgrade raised ProgrammingError
        mock_fix.assert_awaited_once()

    @patch("src.database.init_db._detect_and_fix_broken_state", new_callable=AsyncMock)
    @patch("src.database.init_db.asyncio.to_thread")
    async def test_propagates_non_programming_errors(self, mock_to_thread, mock_fix):
        """Non-ProgrammingError exceptions propagate."""
        mock_to_thread.side_effect = RuntimeError("Unexpected error")

        from src.database.init_db import run_migrations

        with pytest.raises(RuntimeError, match="Unexpected error"):
            await run_migrations()
