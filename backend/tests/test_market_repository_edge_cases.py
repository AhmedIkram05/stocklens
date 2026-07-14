"""
Tests for market repository edge cases (src.market.repository).

Uses real database via connection_ctx() with per-test transaction rollback.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.market.repository import (
    get_earliest_ohlcv_date,
    get_latest_ohlcv_date,
    get_ohlcv,
    get_ohlcv_batch,
    ticker_exists_in_db,
    upsert_ohlcv,
)

NULL_OHLCV = {k: None for k in ("open", "high", "low", "close", "adjusted_close", "volume")}


class TestUpsertOHLCV:
    """Tests for upsert_ohlcv edge cases."""

    async def test_empty_batch_returns_zero(self):
        result = await upsert_ohlcv("AAPL", [])
        assert result == 0

    async def test_single_row(self):
        rows = [{"date": date(2024, 1, 2), "close": Decimal("185"), **NULL_OHLCV}]
        result = await upsert_ohlcv("AAPL", rows)
        assert result == 1

    async def test_batch_size_3000_triggers_batching(self):
        """3000+ rows should trigger batch logic (BATCH_SIZE=3000)."""
        rows = [
            {"date": date(2024, 1, i), "close": Decimal(str(180 + i % 10)), **NULL_OHLCV}
            for i in range(2, 3005)  # 3003 rows
        ]
        result = await upsert_ohlcv("AAPL", rows)
        assert result == 3003

    async def test_duplicate_rows_ignored(self):
        rows = [{"date": date(2024, 1, 2), "close": Decimal("185"), **NULL_OHLCV}]
        await upsert_ohlcv("AAPL", rows)
        result = await upsert_ohlcv("AAPL", rows)  # duplicate
        assert result == 0

    async def test_upsert_multiple_tickers_independent(self):
        rows = [{"date": date(2024, 1, 2), "close": Decimal("185"), **NULL_OHLCV}]
        await upsert_ohlcv("AAPL", rows)
        await upsert_ohlcv("MSFT", rows)

        aapl_data = await get_ohlcv("AAPL")
        msft_data = await get_ohlcv("MSFT")
        assert len(aapl_data) == 1
        assert len(msft_data) == 1


class TestGetOHLCV:
    """Tests for get_ohlcv with various filters."""

    async def test_empty_result_for_unknown_ticker(self):
        result = await get_ohlcv("UNKNOWN")
        assert result == []

    async def test_date_range_filters(self):
        rows = [
            {"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV},
            {"date": date(2024, 1, 3), "close": Decimal("185"), **NULL_OHLCV},
            {"date": date(2024, 1, 4), "close": Decimal("190"), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        result = await get_ohlcv("AAPL", start_date=date(2024, 1, 3), end_date=date(2024, 1, 4))
        assert len(result) == 2
        assert result[0]["date"] == date(2024, 1, 3)
        assert result[1]["date"] == date(2024, 1, 4)

    async def test_start_date_only(self):
        rows = [
            {"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV},
            {"date": date(2024, 1, 5), "close": Decimal("190"), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        result = await get_ohlcv("AAPL", start_date=date(2024, 1, 4))
        assert len(result) == 1
        assert result[0]["date"] == date(2024, 1, 5)

    async def test_end_date_only(self):
        rows = [
            {"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV},
            {"date": date(2024, 1, 5), "close": Decimal("190"), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        result = await get_ohlcv("AAPL", end_date=date(2024, 1, 3))
        assert len(result) == 1
        assert result[0]["date"] == date(2024, 1, 2)

    async def test_limit_and_offset(self):
        rows = [
            {"date": date(2024, 1, i), "close": Decimal(str(180 + i)), **NULL_OHLCV}
            for i in range(2, 7)  # 5 rows
        ]
        await upsert_ohlcv("AAPL", rows)

        page1 = await get_ohlcv("AAPL", limit=2, offset=0)
        page2 = await get_ohlcv("AAPL", limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["date"] == date(2024, 1, 2)
        assert page2[0]["date"] == date(2024, 1, 4)

    async def test_order_by_date_asc(self):
        rows = [
            {"date": date(2024, 1, 5), "close": Decimal("190"), **NULL_OHLCV},
            {"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        result = await get_ohlcv("AAPL")
        assert result[0]["date"] == date(2024, 1, 2)
        assert result[1]["date"] == date(2024, 1, 5)


class TestTickerExists:
    """Tests for ticker_exists_in_db."""

    async def test_unknown_ticker_returns_false(self):
        assert await ticker_exists_in_db("UNKNOWN") is False

    async def test_existing_ticker_returns_true(self):
        rows = [{"date": date(2024, 1, 2), "close": Decimal("185"), **NULL_OHLCV}]
        await upsert_ohlcv("AAPL", rows)
        assert await ticker_exists_in_db("AAPL") is True


class TestGetLatestOHLCVDate:
    """Tests for get_latest_ohlcv_date."""

    async def test_no_data_returns_none(self):
        assert await get_latest_ohlcv_date("UNKNOWN") is None

    async def test_returns_most_recent_date(self):
        rows = [
            {"date": date(2024, 1, 2), **NULL_OHLCV},
            {"date": date(2024, 1, 5), **NULL_OHLCV},
            {"date": date(2024, 1, 3), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)
        latest = await get_latest_ohlcv_date("AAPL")
        assert latest == date(2024, 1, 5)


class TestGetEarliestOHLCVDate:
    """Tests for get_earliest_ohlcv_date."""

    async def test_no_data_returns_none(self):
        assert await get_earliest_ohlcv_date("UNKNOWN") is None

    async def test_returns_oldest_date(self):
        rows = [
            {"date": date(2024, 1, 5), **NULL_OHLCV},
            {"date": date(2024, 1, 2), **NULL_OHLCV},
            {"date": date(2024, 1, 3), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)
        earliest = await get_earliest_ohlcv_date("AAPL")
        assert earliest == date(2024, 1, 2)


class TestGetOHLCVBatch:
    """Tests for get_ohlcv_batch (multi-ticker query)."""

    async def test_empty_tickers_returns_empty_dict(self):
        result = await get_ohlcv_batch([])
        assert result == {}

    async def test_multiple_tickers(self):
        rows = [{"date": date(2024, 1, 2), "close": Decimal("185"), **NULL_OHLCV}]
        await upsert_ohlcv("AAPL", rows)
        await upsert_ohlcv("MSFT", rows)

        result = await get_ohlcv_batch(["AAPL", "MSFT"])
        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result["AAPL"]) == 1
        assert len(result["MSFT"]) == 1

    async def test_date_range_applies_to_all_tickers(self):
        rows = [
            {"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV},
            {"date": date(2024, 1, 5), "close": Decimal("190"), **NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)
        await upsert_ohlcv("MSFT", rows)

        result = await get_ohlcv_batch(["AAPL", "MSFT"], start_date=date(2024, 1, 3))
        assert len(result["AAPL"]) == 1
        assert result["AAPL"][0]["date"] == date(2024, 1, 5)
        assert len(result["MSFT"]) == 1
        assert result["MSFT"][0]["date"] == date(2024, 1, 5)

    async def test_limit_applies_to_total(self):
        rows = [
            {"date": date(2024, 1, i), "close": Decimal(str(180 + i)), **NULL_OHLCV}
            for i in range(2, 7)
        ]
        await upsert_ohlcv("AAPL", rows)
        await upsert_ohlcv("MSFT", rows)

        result = await get_ohlcv_batch(["AAPL", "MSFT"], limit=3)
        total = sum(len(v) for v in result.values())
        assert total <= 3


class TestConcurrencyEdgeCases:
    """Ponytail: concurrent upserts for same ticker may race.
    ON CONFLICT DO NOTHING prevents corruption; just verify no exception."""

    async def test_rapid_sequential_upserts_same_ticker(self):
        """Simulate near-concurrent inserts."""
        rows1 = [{"date": date(2024, 1, 2), "close": Decimal("180"), **NULL_OHLCV}]
        rows2 = [{"date": date(2024, 1, 3), "close": Decimal("185"), **NULL_OHLCV}]
        await upsert_ohlcv("AAPL", rows1)
        await upsert_ohlcv("AAPL", rows2)

        result = await get_ohlcv("AAPL")
        assert len(result) == 2
