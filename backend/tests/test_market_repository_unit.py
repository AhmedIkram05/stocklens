"""DB-free unit tests for src.market.repository (query shape).

The repository behaviour suite (test_market_repository_edge_cases.py) runs
against the test database in CI; these tests pin the get_ohlcv_batch SQL
shape locally by stubbing connection_ctx with a recording cursor.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


def _recording_conn_ctx(captured: dict):
    """connection_ctx stand-in that records the last fetch() call."""

    async def _capture_fetch(query, *args):
        captured["query"] = query
        captured["args"] = args
        return []

    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=_capture_fetch)
    ctx = MagicMock()
    ctx.return_value.__aenter__ = AsyncMock(return_value=conn)
    ctx.return_value.__aexit__ = AsyncMock(return_value=None)
    return ctx


async def test_get_ohlcv_batch_caps_rows_per_ticker():
    from src.market.repository import get_ohlcv_batch

    captured: dict = {}
    with patch("src.market.repository.connection_ctx", _recording_conn_ctx(captured)):
        await get_ohlcv_batch(["AAPL", "MSFT"], start_date=date(2024, 1, 1), limit=50000)

    query = captured["query"]
    # Per-ticker window cap instead of a single global LIMIT
    assert "ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC)" in query
    assert "rn <= $" in query
    assert "LIMIT $" not in query
    # Shape preserved for build_price_map: full column list, ticker+date ASC
    assert "SELECT ticker, date, open, high, low, close, adjusted_close, volume" in query
    assert "ORDER BY ticker, date ASC" in query
    assert captured["args"][-1] == 50000


async def test_get_ohlcv_batch_empty_tickers_short_circuits():
    from src.market.repository import get_ohlcv_batch

    captured: dict = {}
    with patch("src.market.repository.connection_ctx", _recording_conn_ctx(captured)):
        result = await get_ohlcv_batch([])

    assert result == {}
    assert "query" not in captured  # no query issued
