"""
Repository layer for the ohlcv_prices table.

All runtime queries use raw asyncpg (same pattern as Phase 1).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from src.database.connection import connection_ctx


async def get_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    *,
    limit: int = 2000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return OHLCV rows for *ticker*, ordered by date ascending.

    Returns empty list when no data exists.
    """
    conditions = ["ticker = $1"]
    params: list[Any] = [ticker]
    idx = 2

    if start_date:
        conditions.append(f"date >= ${idx}::date")
        params.append(start_date)
        idx += 1
    if end_date:
        conditions.append(f"date <= ${idx}::date")
        params.append(end_date)
        idx += 1

    query = (
        "SELECT date, open, high, low, close, adjusted_close, volume "
        f"FROM ohlcv_prices WHERE {' AND '.join(conditions)} "
        "ORDER BY date ASC"
        f" LIMIT ${idx} OFFSET ${idx + 1}"
    )
    params.extend([limit, offset])

    async with connection_ctx() as conn:
        rows = await conn.fetch(query, *params)

    return [dict(r) for r in rows]


async def get_latest_ohlcv_date(ticker: str) -> Optional[date]:
    """Return the most recent date in ohlcv_prices for *ticker*, or None."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT MAX(date) AS max_date FROM ohlcv_prices WHERE ticker = $1",
            ticker,
        )
    return row["max_date"] if row and row["max_date"] else None


async def upsert_ohlcv(ticker: str, rows: list[dict[str, Any]]) -> int:
    """Insert OHLCV rows using INSERT … ON CONFLICT DO NOTHING.

    Uses a single multi-row ``INSERT`` for one round trip.
    Returns count of inserted rows.

    Note (ponytail): concurrent cache misses for the same ticker may race here.
    ``ON CONFLICT DO NOTHING`` prevents corruption. Add a per-ticker
    ``asyncio.Lock`` if racing becomes a concern.
    """
    if not rows:
        return 0

    # Flatten params: multi-row INSERT uses positional placeholders
    params: list[Any] = []
    for r in rows:
        params.extend([
            ticker,
            r["date"],
            r.get("open"),
            r.get("high"),
            r.get("low"),
            r.get("close"),
            r.get("adjusted_close"),
            r.get("volume"),
        ])

    n_cols = 8
    placeholders = ", ".join(
        f"(${i * n_cols + 1}, ${i * n_cols + 2}::date, ${i * n_cols + 3}::numeric, "
        f"${i * n_cols + 4}::numeric, ${i * n_cols + 5}::numeric, "
        f"${i * n_cols + 6}::numeric, ${i * n_cols + 7}::numeric, ${i * n_cols + 8}::bigint)"
        for i in range(len(rows))
    )

    query = (
        "INSERT INTO ohlcv_prices "
        "(ticker, date, open, high, low, close, adjusted_close, volume) "
        f"VALUES {placeholders} "
        "ON CONFLICT (ticker, date) DO NOTHING"
    )

    async with connection_ctx() as conn:
        status = await conn.execute(query, *params)
    # conn.execute returns a status tag like "INSERT 0 5"
    count = int(status.split()[-1]) if status and status.startswith("INSERT") else 0
    return count


async def ticker_exists_in_db(ticker: str) -> bool:
    """Check if any OHLCV data exists for this ticker."""
    async with connection_ctx() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM ohlcv_prices WHERE ticker = $1 LIMIT 1",
            ticker,
        )
    return row is not None
