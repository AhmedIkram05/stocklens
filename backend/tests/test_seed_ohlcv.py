"""Unit tests for the OHLCV ingest script."""

from __future__ import annotations

from datetime import date

from scripts.seed_ohlcv import insert_rows, resolve_tickers


def test_all_expands_to_full_universe() -> None:
    tickers = resolve_tickers("ALL")
    assert len(tickers) > 100
    assert "SPY" in tickers
    assert len(tickers) == len(set(tickers))


def test_insert_rows_updates_restated_bars() -> None:
    executed: list[tuple[str, list[tuple]]] = []

    class _Cursor:
        def executemany(self, sql, values):
            executed.append((sql, values))

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            pass

    insert_rows(
        _Conn(),
        [
            {
                "ticker": "AAPL",
                "date": date(2026, 1, 2),
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "adjusted_close": 1.4,
                "volume": 10,
            }
        ],
    )
    sql = executed[0][0]
    assert "DO UPDATE SET" in sql
    assert "COALESCE(EXCLUDED.adjusted_close, ohlcv_prices.adjusted_close)" in sql
