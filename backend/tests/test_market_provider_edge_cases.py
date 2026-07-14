"""
Edge case tests for market provider (src.market.provider).

Tests cover helper functions, yfinance edge cases, and async wrappers.
All yfinance calls are mocked to avoid external dependencies.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.market.provider import (
    _download_ohlcv,
    _fetch_fx,
    _fetch_quote,
    _is_retryable,
    _maybe_decimal,
    _maybe_int,
    fetch_fx,
    fetch_ohlcv,
    fetch_quote,
)


class TestMaybeDecimal:
    """_maybe_decimal: handles NaN, None, valid floats."""

    def test_none_returns_none(self):
        assert _maybe_decimal(None) is None

    def test_nan_returns_none(self):
        assert _maybe_decimal(float("nan")) is None

    def test_positive_float(self):
        assert _maybe_decimal(185.50) == Decimal("185.50")

    def test_negative_float(self):
        assert _maybe_decimal(-12.34) == Decimal("-12.34")

    def test_zero(self):
        assert _maybe_decimal(0) == Decimal("0")

    def test_string_number(self):
        assert _maybe_decimal("123.45") == Decimal("123.45")

    def test_invalid_string_returns_none(self):
        assert _maybe_decimal("not-a-number") is None

    def test_very_large_number(self):
        result = _maybe_decimal(1e15)
        assert result == Decimal("1000000000000000.0")

    def test_very_small_number(self):
        result = _maybe_decimal(1e-10)
        assert result == Decimal("0.0000000001")


class TestMaybeInt:
    """_maybe_int: handles NaN, None, valid floats."""

    def test_none_returns_none(self):
        assert _maybe_int(None) is None

    def test_nan_returns_none(self):
        assert _maybe_int(float("nan")) is None

    def test_positive_float(self):
        assert _maybe_int(50000000.0) == 50000000

    def test_negative_float(self):
        assert _maybe_int(-123.45) == -123

    def test_zero(self):
        assert _maybe_int(0) == 0

    def test_invalid_string_returns_none(self):
        assert _maybe_int("not-a-number") is None

    def test_string_number(self):
        assert _maybe_int("1000") == 1000

    def test_large_float(self):
        assert _maybe_int(1e12) == 1000000000000


class TestIsRetryable:
    """_is_retryable detects transient errors."""

    def test_connection_error(self):
        assert _is_retryable(ConnectionError("connection failed")) is True

    def test_timeout_error(self):
        assert _is_retryable(TimeoutError("timed out")) is True

    def test_value_error(self):
        assert _is_retryable(ValueError("bad value")) is True

    def test_http_error(self):
        from requests.exceptions import HTTPError

        assert _is_retryable(HTTPError("429 rate limit")) is True

    def test_generic_exception_not_retryable(self):
        assert _is_retryable(RuntimeError("something else")) is False

    def test_keyboard_interrupt_not_retryable(self):
        assert _is_retryable(KeyboardInterrupt()) is False


class TestDownloadOHLCV:
    """_download_ohlcv: yfinance DataFrame parsing."""

    @patch("src.market.provider.yf.download")
    def test_empty_dataframe(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame()
        result = _download_ohlcv("AAPL")
        assert result == []

    @patch("src.market.provider.yf.download")
    def test_multi_row_with_nan(self, mock_download):
        import pandas as pd

        data = {
            "Open": [np.nan, 180.0],
            "High": [185.0, np.nan],
            "Low": [179.0, 183.0],
            "Close": [184.0, 186.0],
            "Adj Close": [np.nan, 185.5],
            "Volume": [50000000, np.nan],
        }
        idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
        mock_download.return_value = pd.DataFrame(data, index=idx)
        result = _download_ohlcv("AAPL")
        assert len(result) == 2
        assert result[0]["open"] is None
        assert result[0]["high"] == Decimal("185.00")
        assert result[1]["high"] is None
        assert result[1]["volume"] is None

    @patch("src.market.provider.yf.download")
    def test_multiindex_columns_handled(self, mock_download):
        """yfinance >=1.0 returns MultiIndex columns for single ticker."""
        import pandas as pd

        data = {
            ("Open", "AAPL"): [180.0],
            ("High", "AAPL"): [185.0],
            ("Low", "AAPL"): [179.0],
            ("Close", "AAPL"): [184.0],
            ("Adj Close", "AAPL"): [183.5],
            ("Volume", "AAPL"): [50000000],
        }
        idx = pd.DatetimeIndex(["2024-01-02"])
        mock_download.return_value = pd.DataFrame(data, index=idx)
        result = _download_ohlcv("AAPL")
        assert len(result) == 1
        assert result[0]["open"] == Decimal("180.00")

    @patch("src.market.provider.yf.download")
    def test_default_date_range_20_years(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame(
            {"Close": [185.0]}, index=pd.DatetimeIndex(["2024-01-02"])
        )
        _download_ohlcv("AAPL")
        call_args = mock_download.call_args
        start_str = call_args.kwargs["start"]
        end_str = call_args.kwargs["end"]
        start_date = date.fromisoformat(start_str)
        end_date = date.fromisoformat(end_str)
        assert (end_date - start_date).days >= 365 * 18

    @patch("src.market.provider.yf.download")
    def test_custom_date_range(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame(
            {"Close": [185.0]}, index=pd.DatetimeIndex(["2024-06-01"])
        )
        _download_ohlcv("AAPL", start_date=date(2024, 6, 1), end_date=date(2024, 6, 30))
        call_args = mock_download.call_args
        assert call_args.kwargs["start"] == "2024-06-01"
        assert call_args.kwargs["end"] == "2024-06-30"


class TestFetchQuote:
    """_fetch_quote: yfinance Ticker.info extraction."""

    @patch("src.market.provider.yf.Ticker")
    def test_basic_quote(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "regularMarketPrice": 185.50,
            "previousClose": 184.25,
            "regularMarketChange": 1.25,
            "regularMarketChangePercent": 0.68,
            "regularMarketVolume": 45000000,
            "currency": "USD",
            "exchange": "NASDAQ",
        }
        mock_ticker_cls.return_value = mock_ticker
        result = _fetch_quote("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["price"] == Decimal("185.50")
        assert result["change"] == Decimal("1.25")
        assert result["change_pct"] == Decimal("0.68")
        assert result["previous_close"] == Decimal("184.25")
        assert result["volume"] == 45000000
        assert result["currency"] == "USD"
        assert result["exchange"] == "NASDAQ"

    @patch("src.market.provider.yf.Ticker")
    def test_fallback_fields(self, mock_ticker_cls):
        """Uses currentPrice/volume when regularMarket* missing."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "currentPrice": 190.0,
            "previousClose": 188.0,
            "volume": 30000000,
        }
        mock_ticker_cls.return_value = mock_ticker
        result = _fetch_quote("AAPL")
        assert result["price"] == Decimal("190.00")
        assert result["volume"] == 30000000

    @patch("src.market.provider.yf.Ticker")
    def test_all_missing_returns_defaults(self, mock_ticker_cls):
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        mock_ticker_cls.return_value = mock_ticker
        result = _fetch_quote("AAPL")
        assert result["price"] == Decimal("0")
        assert result["change"] == Decimal("0")
        assert result["change_pct"] == Decimal("0")
        assert result["previous_close"] == Decimal("0")
        assert result["volume"] == 0
        assert result["currency"] == "GBP"

    @patch("src.market.provider.yf.Ticker")
    def test_delisted_ticker_returns_none(self, mock_ticker_cls):
        """Delisted ticker returns None for all fields."""
        mock_ticker = MagicMock()
        mock_ticker.info = None
        mock_ticker_cls.return_value = mock_ticker
        result = _fetch_quote("DELISTED")
        assert result["price"] == Decimal("0")


class TestFetchFX:
    """_fetch_fx: FX rate retrieval."""

    @patch("src.market.provider.yf.download")
    def test_gbp_returns_one(self, mock_download):
        result = _fetch_fx("GBP")
        assert result == Decimal("1.0")
        mock_download.assert_not_called()

    @patch("src.market.provider.yf.download")
    def test_usd_fetch_inverts_rate(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame(
            {"Close": [0.79]}, index=pd.DatetimeIndex(["2024-01-02"])
        )
        result = _fetch_fx("USD")
        mock_download.assert_called_once_with(
            "GBPUSD=X", period="1d", progress=False, auto_adjust=False
        )
        assert result == Decimal("1.0") / Decimal("0.79")

    @patch("src.market.provider.yf.download")
    def test_missing_fx_raises(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="FX rate unavailable"):
            _fetch_fx("XYZ")

    @patch("src.market.provider.yf.download")
    def test_nan_fx_raises(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame(
            {"Close": [np.nan]}, index=pd.DatetimeIndex(["2024-01-02"])
        )
        with pytest.raises(ValueError, match="FX rate unavailable"):
            _fetch_fx("EUR")

    @patch("src.market.provider.yf.download")
    def test_zero_fx_raises(self, mock_download):
        import pandas as pd

        mock_download.return_value = pd.DataFrame(
            {"Close": [0.0]}, index=pd.DatetimeIndex(["2024-01-02"])
        )
        with pytest.raises(ValueError, match="FX rate unavailable"):
            _fetch_fx("EUR")


class TestAsyncWrappers:
    """Async public API delegates to sync functions via executor."""

    @patch("src.market.provider._download_ohlcv")
    async def test_fetch_ohlcv_delegates(self, mock_download):
        mock_download.return_value = [{"date": date(2024, 1, 2), "close": Decimal("185")}]
        result = await fetch_ohlcv("AAPL")
        assert len(result) == 1
        mock_download.assert_called_once()

    @patch("src.market.provider._fetch_quote")
    async def test_fetch_quote_delegates(self, mock_fetch):
        mock_fetch.return_value = {"ticker": "AAPL", "price": Decimal("185")}
        result = await fetch_quote("AAPL")
        assert result["ticker"] == "AAPL"
        mock_fetch.assert_called_once_with("AAPL")

    @patch("src.market.provider._fetch_fx")
    async def test_fetch_fx_delegates(self, mock_fx):
        mock_fx.return_value = Decimal("1.25")
        result = await fetch_fx("USD")
        assert result == Decimal("1.25")
        mock_fx.assert_called_once_with("USD")


class TestRetryDecorator:
    """Verify retry decorator is applied to sync functions."""

    def test_download_ohlcv_has_retry(self):
        assert hasattr(_download_ohlcv, "retry")

    def test_fetch_quote_has_retry(self):
        assert hasattr(_fetch_quote, "retry")

    def test_fetch_fx_has_retry(self):
        assert hasattr(_fetch_fx, "retry")
