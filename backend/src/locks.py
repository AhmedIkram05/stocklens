"""Per-portfolio write serialization shared by the transactions and holdings routers.

The M11 invariant — a holding backed by transactions must not be mutated by the
holdings API — is enforced by reading ``transactions`` and writing ``holdings``
atomically while holding the portfolio's transaction-scoped advisory lock. Both
write paths must therefore agree on one lock, or the guard can be raced.

The lock is *try*-acquired in a bounded loop. An unbounded
``pg_advisory_xact_lock`` wait had no ceiling: a contended or leaked holder
stalled the request — and, under pytest (no ``pytest-timeout``), the whole
worker — until GitHub's 6h job cap. Nothing here weakens the mutual exclusion;
it only turns an indefinite wait into a retryable 409.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import asyncpg
from fastapi import HTTPException, status

# A production write holds the lock for one short transaction; this bounds the
# pathological case (a stuck holder) rather than blocking forever.
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.05


@asynccontextmanager
async def portfolio_write(conn: asyncpg.Connection):
    """Run a portfolio write in a transaction, or in the caller's open one.

    ``asyncpg`` refuses ``conn.transaction()`` inside a manually started
    ``BEGIN`` (a raw ``conn.execute("BEGIN")`` — what ``tests/conftest`` does)
    with ``InterfaceError``. The transactions router handled that case; the
    holdings router did not, so its write path failed under the test harness.
    Reusing an already-open transaction keeps the advisory lock scoped the same
    way in tests and production.
    """
    if conn.is_in_transaction():
        yield conn
    else:
        async with conn.transaction():
            yield conn


async def lock_portfolio(conn: asyncpg.Connection, portfolio_id) -> None:
    """Take the portfolio's advisory lock, giving up after a bounded wait.

    Re-entrant within a transaction, so a write path that already holds the
    lock for this portfolio (e.g. the BUY that created the holding) proceeds
    without a spurious conflict.
    """
    key = str(portfolio_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _LOCK_TIMEOUT_SECONDS
    while not await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtext($1))", key):
        if loop.time() >= deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Portfolio is busy with another write; retry shortly.",
            )
        await asyncio.sleep(_LOCK_POLL_SECONDS)
