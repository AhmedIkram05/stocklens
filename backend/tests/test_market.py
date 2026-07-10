"""
Tests for the market data module.

Covers provider helpers, yfinance wrapper (mocked), repository CRUD (real DB),
and router endpoints (mocked yfinance, optional Redis).

Database access runs inside the per-test transaction (conftest._test_db).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

# Fields that default to None in OHLCVData — used to keep test rows compact
_NULL_OHLCV = {k: None for k in ("open", "high", "low", "close", "adjusted_close", "volume")}

# ──────────────────────────────────────────────────────────────────────
# Provider helpers — _maybe_decimal / _maybe_int
# ──────────────────────────────────────────────────────────────────────


class TestMaybeDecimal:
    """_maybe_decimal: NaN/None/valid float → Decimal or None."""

    def test_none_returns_none(self):
        from src.market.provider import _maybe_decimal

        assert _maybe_decimal(None) is None

    def test_nan_returns_none(self):
        from src.market.provider import _maybe_decimal

        assert _maybe_decimal(float("nan")) is None

    def test_float_converted(self):
        from src.market.provider import _maybe_decimal

        assert _maybe_decimal(185.50) == Decimal("185.50")

    def test_int_string_converted(self):
        from src.market.provider import _maybe_decimal

        assert _maybe_decimal("123.45") == Decimal("123.45")

    def test_zero(self):
        from src.market.provider import _maybe_decimal

        assert _maybe_decimal(0) == Decimal("0")


class TestMaybeInt:
    """_maybe_int: NaN/None/valid float → int or None."""

    def test_none_returns_none(self):
        from src.market.provider import _maybe_int

        assert _maybe_int(None) is None

    def test_nan_returns_none(self):
        from src.market.provider import _maybe_int

        assert _maybe_int(float("nan")) is None

    def test_float_converted(self):
        from src.market.provider import _maybe_int

        assert _maybe_int(50000000.0) == 50000000

    def test_invalid_returns_none(self):
        from src.market.provider import _maybe_int

        assert _maybe_int("not-a-number") is None


# ──────────────────────────────────────────────────────────────────────
# Provider — _download_ohlcv (yfinance wrapper, mocked)
# ──────────────────────────────────────────────────────────────────────


class TestDownloadOHLCV:
    """_download_ohlcv DataFrame parsing (yf.download mocked)."""

    @patch("src.market.provider.yf.download")
    def test_empty_dataframe(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame()

        from src.market.provider import _download_ohlcv

        result = _download_ohlcv("AAPL")
        assert result == []

    @patch("src.market.provider.yf.download")
    def test_multi_row(self, mock_download):
        import pandas as pd

        data = {
            "Open": [180.0, 184.5],
            "High": [185.0, 187.0],
            "Low": [179.0, 183.0],
            "Close": [184.0, 186.0],
            "Adj Close": [183.5, 185.5],
            "Volume": [50000000, 45000000],
        }
        idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
        mock_download.return_value = pd.DataFrame(data, index=idx)

        from src.market.provider import _download_ohlcv

        result = _download_ohlcv("AAPL")
        assert len(result) == 2
        assert result[0]["date"] == date(2024, 1, 2)
        assert result[0]["close"] == Decimal("184.00")
        assert result[0]["volume"] == 50000000
        assert result[1]["date"] == date(2024, 1, 3)
        assert result[1]["close"] == Decimal("186.00")

    @patch("src.market.provider.yf.download")
    def test_nan_fields_become_none(self, mock_download):
        """Row-level NaN → None conversion works."""
        import numpy as np
        import pandas as pd

        data = {
            "Open": [np.nan],
            "High": [np.nan],
            "Low": [np.nan],
            "Close": [185.0],
            "Adj Close": [np.nan],
            "Volume": [np.nan],
        }
        idx = pd.DatetimeIndex(["2024-01-02"])
        mock_download.return_value = pd.DataFrame(data, index=idx)

        from src.market.provider import _download_ohlcv

        result = _download_ohlcv("AAPL")
        assert len(result) == 1
        assert result[0]["open"] is None
        assert result[0]["high"] is None
        assert result[0]["low"] is None
        assert result[0]["close"] == Decimal("185.00")
        assert result[0]["adjusted_close"] is None
        assert result[0]["volume"] is None


# ──────────────────────────────────────────────────────────────────────
# Provider — _fetch_quote (yfinance Ticker.info, mocked)
# ──────────────────────────────────────────────────────────────────────


class TestFetchQuote:
    """_fetch_quote info field extraction (yf.Ticker mocked)."""

    @patch("src.market.provider.yf.Ticker")
    def test_basic_quote(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 185.50,
            "previousClose": 184.25,
            "regularMarketChange": 1.25,
            "regularMarketChangePercent": 0.68,
            "regularMarketVolume": 45000000,
        }
        mock_ticker_cls.return_value = mock_ticker

        from src.market.provider import _fetch_quote

        result = _fetch_quote("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["price"] == Decimal("185.50")
        assert result["change"] == Decimal("1.25")
        assert result["change_pct"] == Decimal("0.68")
        assert result["previous_close"] == Decimal("184.25")
        assert result["volume"] == 45000000
        assert isinstance(result["timestamp"], datetime)

    @patch("src.market.provider.yf.Ticker")
    def test_fallback_fields(self, mock_ticker_cls):
        """Uses currentPrice / volume fallback when regularMarket* missing."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "currentPrice": 190.0,
            "previousClose": 188.0,
            "volume": 30000000,
        }
        mock_ticker_cls.return_value = mock_ticker

        from src.market.provider import _fetch_quote

        result = _fetch_quote("AAPL")
        assert result["price"] == Decimal("190.00")
        assert result["volume"] == 30000000

    @patch("src.market.provider.yf.Ticker")
    def test_all_missing_returns_defaults(self, mock_ticker_cls):
        """Empty info dict defaults to 0."""
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_ticker_cls.return_value = mock_ticker

        from src.market.provider import _fetch_quote

        result = _fetch_quote("AAPL")
        assert result["price"] == Decimal("0")
        assert result["change"] == Decimal("0")
        assert result["volume"] == 0


# ──────────────────────────────────────────────────────────────────────
# Provider — async fetch_ohlcv / fetch_quote
# ──────────────────────────────────────────────────────────────────────


class TestFetchOHLCVAsync:
    """Async fetch_ohlcv delegates to _download_ohlcv via executor."""

    @patch("src.market.provider._download_ohlcv")
    async def test_fetch_ohlcv_defaults(self, mock_download):
        """Default date range is 1 year."""
        mock_download.return_value = [{"date": date(2024, 1, 2)}]

        from src.market.provider import fetch_ohlcv

        result = await fetch_ohlcv("AAPL")

        assert len(result) == 1
        # Verify _download_ohlcv was called with default dates
        call_args = mock_download.call_args
        assert call_args[0][0] == "AAPL"
        assert call_args[0][1] is not None  # start_date
        assert call_args[0][2] is not None  # end_date

    @patch("src.market.provider._fetch_quote")
    async def test_fetch_quote_delegates(self, mock_fetch):
        mock_fetch.return_value = {"ticker": "AAPL"}

        from src.market.provider import fetch_quote

        result = await fetch_quote("AAPL")
        assert result["ticker"] == "AAPL"
        mock_fetch.assert_called_once_with("AAPL")


# ──────────────────────────────────────────────────────────────────────
# Repository integration tests (real DB, rolled back per test)
# ──────────────────────────────────────────────────────────────────────


class TestRepositoryOHLCV:
    """Repository layer — direct DB calls (no yfinance involved)."""

    async def test_get_ohlcv_empty(self):
        """No data for an unknown ticker returns []."""
        from src.market.repository import get_ohlcv

        result = await get_ohlcv("UNKNOWNTICKER")
        assert result == []

    async def test_upsert_and_get(self):
        """Insert rows then retrieve them."""
        from src.market.repository import get_ohlcv, upsert_ohlcv

        rows = [
            {
                "date": date(2024, 1, 2),
                "open": Decimal("180"),
                "high": Decimal("185"),
                "low": Decimal("179"),
                "close": Decimal("184"),
                "adjusted_close": Decimal("183.5"),
                "volume": 50000000,
            },
            {
                "date": date(2024, 1, 3),
                "open": Decimal("184.5"),
                "high": Decimal("187"),
                "low": Decimal("183"),
                "close": Decimal("186"),
                "adjusted_close": Decimal("185.5"),
                "volume": 45000000,
            },
        ]
        inserted = await upsert_ohlcv("AAPL", rows)
        assert inserted == 2

        result = await get_ohlcv("AAPL")
        assert len(result) == 2
        assert result[0]["date"] == date(2024, 1, 2)
        assert result[1]["date"] == date(2024, 1, 3)

    async def test_upsert_idempotent(self):
        """Duplicate rows are silently ignored (ON CONFLICT DO NOTHING)."""
        from src.market.repository import get_ohlcv, upsert_ohlcv

        rows = [
            {
                "date": date(2024, 1, 2),
                "open": Decimal("180"),
                "high": Decimal("185"),
                "low": Decimal("179"),
                "close": Decimal("184"),
                "adjusted_close": Decimal("183.5"),
                "volume": 50000000,
            },
        ]
        assert await upsert_ohlcv("AAPL", rows) == 1
        assert await upsert_ohlcv("AAPL", rows) == 0  # no new rows

        result = await get_ohlcv("AAPL")
        assert len(result) == 1

    async def test_upsert_empty_list(self):
        """Empty list returns 0."""
        from src.market.repository import upsert_ohlcv

        assert await upsert_ohlcv("AAPL", []) == 0

    async def test_get_ohlcv_with_date_range(self):
        """Date filters return subset."""
        from src.market.repository import get_ohlcv, upsert_ohlcv

        rows = [
            {"date": date(2024, 1, 2), "close": Decimal("184"), **_NULL_OHLCV},
            {"date": date(2024, 1, 3), "close": Decimal("186"), **_NULL_OHLCV},
            {"date": date(2024, 1, 4), "close": Decimal("188"), **_NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        result = await get_ohlcv("AAPL", start_date=date(2024, 1, 3), end_date=date(2024, 1, 4))
        assert len(result) == 2
        assert result[0]["date"] == date(2024, 1, 3)
        assert result[1]["date"] == date(2024, 1, 4)

    async def test_get_latest_ohlcv_date_none(self):
        """No data returns None."""
        from src.market.repository import get_latest_ohlcv_date

        assert await get_latest_ohlcv_date("UNKNOWN") is None

    async def test_get_latest_ohlcv_date(self):
        """Returns the most recent date."""
        from src.market.repository import get_latest_ohlcv_date, upsert_ohlcv

        rows = [
            {"date": date(2024, 1, 2), **_NULL_OHLCV},
            {"date": date(2024, 1, 5), **_NULL_OHLCV},
        ]
        await upsert_ohlcv("AAPL", rows)

        latest = await get_latest_ohlcv_date("AAPL")
        assert latest == date(2024, 1, 5)

    async def test_ticker_exists(self):
        """ticker_exists_in_db returns True/False."""
        from src.market.repository import ticker_exists_in_db, upsert_ohlcv

        assert await ticker_exists_in_db("AAPL") is False

        await upsert_ohlcv(
            "AAPL",
            [
                {"date": date(2024, 1, 2), **_NULL_OHLCV},
            ],
        )
        assert await ticker_exists_in_db("AAPL") is True


# ──────────────────────────────────────────────────────────────────────
# Router — OHLCV endpoint
# ──────────────────────────────────────────────────────────────────────


class TestOHLCVEndpoint:
    """GET /market/ohlcv/{ticker}"""

    async def test_happy_path(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Returns cached OHLCV data from DB (no yfinance call)."""
        from src.market.repository import upsert_ohlcv

        today = date.today()
        rows = [
            {
                "date": today,
                "open": Decimal("180"),
                "high": Decimal("185"),
                "low": Decimal("179"),
                "close": Decimal("184"),
                "adjusted_close": Decimal("183.5"),
                "volume": 50000000,
            },
            {
                "date": today - timedelta(days=1),
                "open": Decimal("178"),
                "high": Decimal("182"),
                "low": Decimal("176"),
                "close": Decimal("180"),
                "adjusted_close": Decimal("179.5"),
                "volume": 48000000,
            },
        ]
        await upsert_ohlcv("AAPL", rows)

        response = await client.get("/market/ohlcv/AAPL", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert data["total"] == 2
        assert len(data["data"]) == 2

    async def test_ticker_uppercased(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Lowercase ticker is uppercased."""
        from src.market.repository import upsert_ohlcv

        today = date.today()
        await upsert_ohlcv(
            "AAPL",
            [
                {"date": today, **_NULL_OHLCV},
            ],
        )

        response = await client.get("/market/ohlcv/aapl", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    async def test_no_data_returns_404(self, client: AsyncClient, auth_headers: dict[str, str]):
        """No price data in DB and no yfinance data → 404."""
        # We need to mock fetch_ohlcv to return empty, and make sure
        # the staleness check triggers (no data in DB = stale).
        with patch("src.market.router.fetch_ohlcv", return_value=[]):
            response = await client.get("/market/ohlcv/UNKNOWN", headers=auth_headers)

        assert response.status_code == 404

    async def test_yfinance_failure_returns_503(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """When yfinance is unreachable and no cache exists → 503."""
        with patch("src.market.router.fetch_ohlcv", side_effect=ConnectionError("yfinance down")):
            response = await client.get("/market/ohlcv/AAPL", headers=auth_headers)

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

    async def test_date_range(self, client: AsyncClient, auth_headers: dict[str, str]):
        """start_date and end_date query params filter results."""
        from src.market.repository import upsert_ohlcv

        today = date.today()
        await upsert_ohlcv(
            "AAPL",
            [
                {
                    "date": today - timedelta(days=5),
                    "close": Decimal("180"),
                    **{k: None for k in ("open", "high", "low", "adjusted_close", "volume")},
                },
                {
                    "date": today - timedelta(days=3),
                    "close": Decimal("185"),
                    **{k: None for k in ("open", "high", "low", "adjusted_close", "volume")},
                },
                {
                    "date": today - timedelta(days=1),
                    "close": Decimal("190"),
                    **{k: None for k in ("open", "high", "low", "adjusted_close", "volume")},
                },
            ],
        )

        start = (today - timedelta(days=4)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
        response = await client.get(
            f"/market/ohlcv/AAPL?start_date={start}&end_date={end}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 2  # day -3 and day -1

    async def test_requires_auth(self, client: AsyncClient):
        """No auth header → 401."""
        response = await client.get("/market/ohlcv/AAPL")
        assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# Router — Quote endpoint
# ──────────────────────────────────────────────────────────────────────


class TestQuoteEndpoint:
    """GET /market/quote/{ticker}"""

    QUOTE_DATA = {
        "ticker": "AAPL",
        "price": Decimal("185.50"),
        "change": Decimal("1.25"),
        "change_pct": Decimal("0.68"),
        "previous_close": Decimal("184.25"),
        "volume": 45000000,
        "timestamp": datetime.now(timezone.utc),
    }

    async def test_happy_path(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Fetches quote via yfinance, caches in Redis, returns response."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with (
            patch("src.market.router.fetch_quote", return_value=self.QUOTE_DATA),
            patch("src.market.router.get_redis", return_value=mock_redis),
        ):
            response = await client.get("/market/quote/AAPL", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert data["price"] == 185.50
        assert data["change"] == 1.25
        assert data["change_pct"] == 0.68
        assert data["volume"] == 45000000

        # Verify Redis setex was called
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][1] == 30  # TTL

    async def test_redis_cache_hit(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Returns cached quote without calling yfinance."""
        import json

        now = datetime.now(timezone.utc)
        cached_json = json.dumps(
            {
                "ticker": "AAPL",
                "price": 185.50,
                "change": 1.25,
                "change_pct": 0.68,
                "previous_close": 184.25,
                "volume": 45000000,
                "timestamp": now.isoformat(),
            }
        )

        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_json

        with patch("src.market.router.get_redis", return_value=mock_redis):
            response = await client.get("/market/quote/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["price"] == 185.50
        # fetch_quote should NOT have been called
        # We verify this by not patching fetch_quote — if it was called, it would fail.

    async def test_redis_unavailable(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Redis down → graceful degradation, fetch from yfinance."""
        with (
            patch("src.market.router.get_redis", side_effect=ConnectionError("Redis down")),
            patch("src.market.router.fetch_quote", return_value=self.QUOTE_DATA),
        ):
            response = await client.get("/market/quote/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["price"] == 185.50

    async def test_yfinance_failure_returns_503(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """yfinance unreachable and no cache → 503."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with (
            patch("src.market.router.get_redis", return_value=mock_redis),
            patch("src.market.router.fetch_quote", side_effect=ConnectionError("yfinance down")),
        ):
            response = await client.get("/market/quote/AAPL", headers=auth_headers)

        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

    async def test_ticker_uppercased(self, client: AsyncClient, auth_headers: dict[str, str]):
        """Lowercase ticker is uppercased in quote endpoint."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with (
            patch("src.market.router.get_redis", return_value=mock_redis),
            patch("src.market.router.fetch_quote", return_value=self.QUOTE_DATA),
        ):
            response = await client.get("/market/quote/aapl", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"

    async def test_requires_auth(self, client: AsyncClient):
        """No auth header → 401."""
        response = await client.get("/market/quote/AAPL")
        assert response.status_code == 401

    async def test_corrupted_cache_skips_and_refetches(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Corrupted JSON in Redis → skip cache, fetch fresh."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not-valid-json{{{"

        with (
            patch("src.market.router.get_redis", return_value=mock_redis),
            patch("src.market.router.fetch_quote", return_value=self.QUOTE_DATA),
        ):
            response = await client.get("/market/quote/AAPL", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["price"] == 185.50
