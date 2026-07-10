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


async def get_earliest_ohlcv_date(ticker: str) -> Optional[date]:
    """Return the oldest date in ohlcv_prices for *ticker*, or None."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT MIN(date) AS min_date FROM ohlcv_prices WHERE ticker = $1",
            ticker,
        )
    return row["min_date"] if row and row["min_date"] else None


async def upsert_ohlcv(ticker: str, rows: list[dict[str, Any]]) -> int:
    """Insert OHLCV rows using INSERT … ON CONFLICT DO NOTHING.

    Batches inserts to stay under asyncpg's 32,767 parameter limit.
    Returns total count of inserted rows.

    Note (ponytail): concurrent cache misses for the same ticker may race here.
    ``ON CONFLICT DO NOTHING`` prevents corruption. Add a per-ticker
    ``asyncio.Lock`` if racing becomes a concern.
    """
    if not rows:
        return 0

    # 8 columns per row. 32767 // 8 = 4095 rows per batch max.
    # Use 3000 for safety margin.
    BATCH_SIZE = 3000
    total_inserted = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]

        params: list[Any] = []
        for r in batch:
            params.extend(
                [
                    ticker,
                    r["date"],
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("adjusted_close"),
                    r.get("volume"),
                ]
            )

        n_cols = 8
        placeholders = ", ".join(
            f"(${i * n_cols + 1}, ${i * n_cols + 2}::date, ${i * n_cols + 3}::numeric, "
            f"${i * n_cols + 4}::numeric, ${i * n_cols + 5}::numeric, "
            f"${i * n_cols + 6}::numeric, ${i * n_cols + 7}::numeric, ${i * n_cols + 8}::bigint)"
            for i in range(len(batch))
        )

        query = (
            "INSERT INTO ohlcv_prices "
            "(ticker, date, open, high, low, close, adjusted_close, volume) "
            f"VALUES {placeholders} "
            "ON CONFLICT (ticker, date) DO NOTHING"
        )

        async with connection_ctx() as conn:
            status = await conn.execute(query, *params)
        count = int(status.split()[-1]) if status and status.startswith("INSERT") else 0
        total_inserted += count

    return total_inserted


async def ticker_exists_in_db(ticker: str) -> bool:
    """Check if any OHLCV data exists for this ticker."""
    async with connection_ctx() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM ohlcv_prices WHERE ticker = $1 LIMIT 1",
            ticker,
        )
    return row is not None


async def get_ohlcv_batch(
    tickers: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    *,
    limit: int = 50000,
) -> dict[str, list[dict[str, Any]]]:
    """Return OHLCV rows for multiple tickers in a single query.

    Returns {ticker: [rows...]} grouped by ticker.
    """
    if not tickers:
        return {}

    conditions = ["ticker = ANY($1::text[])"]
    params: list[Any] = [tickers]
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
        "SELECT ticker, date, open, high, low, close, adjusted_close, volume "
        f"FROM ohlcv_prices WHERE {' AND '.join(conditions)} "
        "ORDER BY ticker, date ASC"
        f" LIMIT ${idx}"
    )
    params.append(limit)

    async with connection_ctx() as conn:
        rows = await conn.fetch(query, *params)

    result: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        t = r["ticker"]
        result.setdefault(t, []).append(dict(r))
    return result
