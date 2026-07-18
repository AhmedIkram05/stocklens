"""
Asyncpg connection pool for runtime database access.

All runtime queries use raw asyncpg — no SQLAlchemy ORM at query time.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

pool: asyncpg.Pool | None = None

# JSONB codec so ``SELECT metrics FROM model_registry`` returns ``dict``
# instead of a raw JSON string.  Registered on every connection in the pool.
_JSONB_CODEC = ("jsonb", "pg_catalog")


async def _init_jsonb_codec(conn: asyncpg.Connection) -> None:
    """Register JSONB decoder so asyncpg returns JSONB columns as dict/list."""
    await conn.set_type_codec(
        _JSONB_CODEC[0],
        encoder=json.dumps,
        decoder=json.loads,
        schema=_JSONB_CODEC[1],
    )


def _normalise_dsn(dsn: str) -> str:
    """Strip the ``+asyncpg`` driver suffix so asyncpg can parse the URL."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> None:
    """Create the global asyncpg connection pool."""
    global pool
    pool = await asyncpg.create_pool(
        _normalise_dsn(dsn),
        min_size=min_size,
        max_size=max_size,
        init=_init_jsonb_codec,
    )


async def get_conn() -> asyncpg.Connection:
    """Acquire a connection from the pool.

    Raises ``RuntimeError`` if the pool has not been initialised.

    Prefer :func:`connection_ctx` (an async context manager) over calling
    this function directly to ensure connections are always returned.
    """
    if pool is None:
        raise RuntimeError("Database pool not initialised")
    return await pool.acquire()


async def release_conn(conn: asyncpg.Connection) -> None:
    """Return a connection to the pool."""
    if pool:
        await pool.release(conn)


@asynccontextmanager
async def connection_ctx() -> AsyncIterator[asyncpg.Connection]:
    """Async context manager that acquires and releases a connection.

    Usage::

        async with connection_ctx() as conn:
            row = await conn.fetchrow("SELECT 1")
    """
    conn = await get_conn()
    try:
        yield conn
    finally:
        await release_conn(conn)


async def close_pool() -> None:
    """Close the global pool and release all resources."""
    global pool
    if pool:
        try:
            await pool.close()
        except RuntimeError:
            # Fall back to terminate if graceful close fails
            # (e.g. pending internal connection-holder tasks or
            # event-loop mismatch in test scenarios).
            pool.terminate()
        pool = None
