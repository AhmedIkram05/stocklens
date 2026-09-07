"""
Tests for the cached quote fetch (``src.market.quotes.get_quote``).

All Redis/provider access is mocked — no network, no services needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

QUOTE_DATA = {
    "ticker": "AAPL",
    "price": Decimal("185.50"),
    "change": Decimal("1.25"),
    "change_pct": Decimal("0.68"),
    "previous_close": Decimal("184.25"),
    "volume": 45000000,
    "timestamp": datetime.now(timezone.utc),
}


class TestGetQuote:
    """get_quote: hit / miss+set / redis-down / corrupt / provider-error."""

    async def test_cache_hit_returns_parsed_quote_without_fetch(self):
        """Redis hit → parsed quote returned; fetch_quote NOT called."""
        from src.market.quotes import get_quote

        cached_json = json.dumps(
            {
                "ticker": "AAPL",
                "price": 185.50,
                "change": 1.25,
                "change_pct": 0.68,
                "previous_close": 184.25,
                "volume": 45000000,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_json

        with (
            patch("src.market.quotes.get_redis", return_value=mock_redis),
            patch("src.market.quotes.fetch_quote") as mock_fetch,
        ):
            quote = await get_quote("aapl")

        assert quote["ticker"] == "AAPL"
        assert quote["price"] == 185.50
        mock_redis.get.assert_awaited_once_with("quote:AAPL")
        mock_fetch.assert_not_called()

    async def test_cache_miss_fetches_and_sets_with_ttl_60(self):
        """Redis miss → fetch_quote → setex(key, 60, json) once."""
        from src.market.quotes import get_quote

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with (
            patch("src.market.quotes.get_redis", return_value=mock_redis),
            patch("src.market.quotes.fetch_quote", return_value=QUOTE_DATA) as mock_fetch,
        ):
            quote = await get_quote("AAPL")

        assert quote == QUOTE_DATA
        mock_fetch.assert_awaited_once_with("AAPL")
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "quote:AAPL"
        assert args[0][1] == 60  # TTL
        assert json.loads(args[0][2])["ticker"] == "AAPL"

    async def test_redis_down_degrades_to_fetch(self):
        """get_redis raises → falls through to fetch_quote → returns data."""
        from src.market.quotes import get_quote

        with (
            patch("src.market.quotes.get_redis", side_effect=ConnectionError("Redis down")),
            patch("src.market.quotes.fetch_quote", return_value=QUOTE_DATA),
        ):
            quote = await get_quote("AAPL")

        assert quote == QUOTE_DATA

    async def test_corrupt_cache_refetches_fresh(self):
        """Unparseable cached value → warning + fresh fetch."""
        from src.market.quotes import get_quote

        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not-json"

        with (
            patch("src.market.quotes.get_redis", return_value=mock_redis),
            patch("src.market.quotes.fetch_quote", return_value=QUOTE_DATA) as mock_fetch,
        ):
            quote = await get_quote("AAPL")

        assert quote == QUOTE_DATA
        mock_fetch.assert_awaited_once_with("AAPL")

    async def test_provider_error_propagates(self):
        """fetch_quote raises → get_quote raises (REST maps to 503)."""
        from src.market.quotes import get_quote

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        with (
            patch("src.market.quotes.get_redis", return_value=mock_redis),
            patch(
                "src.market.quotes.fetch_quote",
                side_effect=ConnectionError("yfinance down"),
            ),
        ):
            try:
                await get_quote("AAPL")
            except ConnectionError:
                pass
            else:
                raise AssertionError("expected ConnectionError to propagate")
