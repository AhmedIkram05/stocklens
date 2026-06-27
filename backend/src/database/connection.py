"""
Asyncpg connection pool for runtime database access.

All runtime queries use raw asyncpg — no SQLAlchemy ORM at query time.
"""

import asyncpg

pool: asyncpg.Pool | None = None


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
    )


async def get_conn() -> asyncpg.Connection:
    """Acquire a connection from the pool.

    Raises ``RuntimeError`` if the pool has not been initialised.
    """
    if pool is None:
        raise RuntimeError("Database pool not initialised")
    return await pool.acquire()


async def release_conn(conn: asyncpg.Connection) -> None:
    """Return a connection to the pool."""
    if pool:
        await pool.release(conn)


async def close_pool() -> None:
    """Close the global pool and release all resources."""
    global pool
    if pool:
        await pool.close()
        pool = None
