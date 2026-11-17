"""
Run Alembic migrations at application startup.

The upgrade is serialised across workers with a Postgres advisory lock: the
loser waits, then runs ``upgrade head`` as a no-op. Failures are never
swallowed, so a database that cannot reach head stops the process instead of
serving against a half-migrated schema.
"""

import asyncio
import logging

import asyncpg
from alembic.command import upgrade
from alembic.config import Config

from src.config import settings

logger = logging.getLogger(__name__)

# "STLN" — stable key; advisory locks are scoped to the database.
_MIGRATION_LOCK_KEY = 0x53544C4E

# Bounded wait for a peer's migration; a hung peer must not block startup forever.
_LOCK_WAIT = "15min"

# The pre-0001 identity bridge. A database stamped here with no ``users``
# table is the old partial-schema state that hand-written DDL used to patch.
_LEGACY_BRIDGE_REVISION = "d2f4e1b3c5a7"


def _normalise_dsn(dsn: str) -> str:
    """Strip the +asyncpg driver suffix so asyncpg can parse the URL."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _migration_dsn() -> str:
    """The database Alembic migrates: the test DB under pytest, else runtime."""
    dsn = settings.TEST_DATABASE_URL if settings.ENVIRONMENT == "test" else settings.DATABASE_URL
    return _normalise_dsn(dsn)


async def _assert_supported_state(conn: asyncpg.Connection) -> None:
    """Refuse the partial-schema state instead of guessing a repair.

    A database stamped at the legacy bridge revision with no ``users`` table
    cannot be upgraded by the chain: 0001 assumes it creates every table. It
    has to be recreated or restored, not patched with hand-written DDL.
    """
    try:
        version = await conn.fetchval("SELECT version_num FROM alembic_version")
    except asyncpg.exceptions.UndefinedTableError:
        return
    if version != _LEGACY_BRIDGE_REVISION:
        return
    existing = await conn.fetchval(
        "SELECT count(*) FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
    )
    if existing == 0:
        return  # 0001 will create every table
    raise RuntimeError(
        f"Database is stamped at the legacy d2f4e1b3c5a7 revision but already has "
        f"{existing} table(s); 0001 creates tables unconditionally and cannot be "
        "re-run. Verify the schema, then run `alembic stamp 0011` (fully migrated) "
        "or `alembic stamp 0001 && alembic upgrade head` (0001-only schema)."
    )


async def run_migrations() -> None:
    """Run all pending Alembic migrations, serialised across workers."""
    alembic_cfg = Config("alembic.ini")
    lock_conn = await asyncpg.connect(_migration_dsn())
    try:
        await lock_conn.execute(f"SET statement_timeout = '{_LOCK_WAIT}'")
        await lock_conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_KEY)
        await lock_conn.execute("SET statement_timeout = 0")
        try:
            await _assert_supported_state(lock_conn)
            await asyncio.to_thread(upgrade, alembic_cfg, "head")
        finally:
            try:
                await lock_conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_KEY)
            except Exception:
                logger.warning("migration_lock_release_failed", exc_info=True)
    finally:
        await lock_conn.close()
