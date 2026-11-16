"""Tests for database initialisation / Alembic migration orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import asyncpg
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


class TestAssertSupportedState:
    """The legacy partial-schema state is refused, not guessed at."""

    async def test_skips_when_version_is_not_the_bridge(self):
        from src.database.init_db import _assert_supported_state

        conn = AsyncMock()
        conn.fetchval.return_value = "0011"

        await _assert_supported_state(conn)

        conn.fetchval.assert_awaited_once_with("SELECT version_num FROM alembic_version")

    async def test_missing_version_table_is_clean(self):
        from src.database.init_db import _assert_supported_state

        conn = AsyncMock()
        conn.fetchval.side_effect = asyncpg.exceptions.UndefinedTableError(
            'relation "alembic_version" does not exist'
        )

        await _assert_supported_state(conn)

    async def test_bridge_with_empty_schema_is_allowed(self):
        from src.database.init_db import _assert_supported_state

        conn = AsyncMock()
        conn.fetchval.side_effect = ["d2f4e1b3c5a7", 0]

        await _assert_supported_state(conn)

    async def test_bridge_with_existing_tables_raises(self):
        from src.database.init_db import _assert_supported_state

        conn = AsyncMock()
        conn.fetchval.side_effect = ["d2f4e1b3c5a7", 3]

        with pytest.raises(RuntimeError, match="already has 3 table"):
            await _assert_supported_state(conn)


class TestRunMigrations:
    """run_migrations serialises the upgrade and never swallows errors."""

    async def test_acquires_lock_runs_upgrade_and_releases(self):
        from src.database.init_db import run_migrations

        conn = AsyncMock()
        conn.fetchval.return_value = "0011"

        with (
            patch("src.database.init_db.asyncpg.connect", AsyncMock(return_value=conn)),
            patch("src.database.init_db.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
        ):
            await run_migrations()

        statements = [call.args[0] for call in conn.execute.await_args_list]
        assert "pg_advisory_lock" in statements[1]
        assert "pg_advisory_unlock" in statements[-1]

        args, _ = to_thread.call_args
        assert args[0].__name__ == "upgrade"
        assert args[2] == "head"
        conn.close.assert_awaited_once()

    async def test_refuses_legacy_state_before_upgrading(self):
        from src.database.init_db import run_migrations

        conn = AsyncMock()
        conn.fetchval.side_effect = ["d2f4e1b3c5a7", 1]

        with (
            patch("src.database.init_db.asyncpg.connect", AsyncMock(return_value=conn)),
            patch("src.database.init_db.asyncio.to_thread", new_callable=AsyncMock) as to_thread,
        ):
            with pytest.raises(RuntimeError, match="legacy d2f4e1b3c5a7"):
                await run_migrations()

        to_thread.assert_not_awaited()
        conn.close.assert_awaited_once()

    async def test_propagates_upgrade_errors(self):
        from src.database.init_db import run_migrations

        conn = AsyncMock()
        conn.fetchval.return_value = "0011"

        with (
            patch("src.database.init_db.asyncpg.connect", AsyncMock(return_value=conn)),
            patch(
                "src.database.init_db.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await run_migrations()

        statements = [call.args[0] for call in conn.execute.await_args_list]
        assert any("pg_advisory_unlock" in stmt for stmt in statements)
        conn.close.assert_awaited_once()

    async def test_unlock_failure_is_logged_not_raised(self):
        from src.database.init_db import run_migrations

        conn = AsyncMock()
        conn.fetchval.return_value = "0011"
        conn.execute.side_effect = [None, None, None, RuntimeError("unlock failed")]

        with (
            patch("src.database.init_db.asyncpg.connect", AsyncMock(return_value=conn)),
            patch("src.database.init_db.asyncio.to_thread", new_callable=AsyncMock),
        ):
            await run_migrations()

        conn.close.assert_awaited_once()
