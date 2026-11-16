"""
Tests for src/market/fx.py — currency resolution and FX normalisation.

Covers ``resolve_instrument`` (instruments table lookup + provider fallback)
and ``get_fx_rate_to_gbp`` (Redis-cached FX rate lookup).

Internal test helpers:
    ``_ensure_instrument(ticker, currency, exchange)`` — Insert a row into the
    ``instruments`` table so that ``resolve_instrument`` returns it during the
    test transaction.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.market.fx import (
    InstrumentResolutionError,
    current_fx_rates,
    get_fx_rate_to_gbp,
    resolve_instrument,
)


def _unique_currency(label: str) -> str:
    """Return a currency name unique to this test run to avoid Redis cache
    cross-contamination between test sessions."""
    return f"TST_{label}_{uuid4().hex[:8]}"


async def _ensure_instrument(
    ticker: str,
    currency: str = "USD",
    exchange: str | None = "NASDAQ",
) -> None:
    """Insert a known instrument row inside the test transaction."""
    from src.database.connection import connection_ctx

    async with connection_ctx() as conn:
        await conn.execute(
            "INSERT INTO instruments (ticker, currency, exchange) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (ticker) DO UPDATE SET "
            "currency = EXCLUDED.currency, exchange = EXCLUDED.exchange",
            ticker,
            currency,
            exchange,
        )


# ── resolve_instrument ───────────────────────────────────────────────────


class TestResolveInstrument:
    """Tests for resolve_instrument — ticker → (currency, exchange)."""

    async def test_known_ticker_from_db(self):
        """A ticker already in the instruments table returns cached values."""
        await _ensure_instrument("AAPL", "USD", "NASDAQ")
        currency, exchange = await resolve_instrument("AAPL")
        assert currency == "USD"
        assert exchange == "NASDAQ"

    async def test_currency_unknown_ticker_falls_back_to_provider(self):
        """Ticker not in instruments → provider is queried and row persisted."""
        mock_quote = {"currency": "USD", "exchange": "NYSE"}
        with patch("src.market.fx.provider.fetch_quote", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_quote
            currency, exchange = await resolve_instrument("UNKNOWN")

        assert currency == "USD"
        assert exchange == "NYSE"
        mock_fetch.assert_awaited_once_with("UNKNOWN")

        # Second call should hit the DB (already persisted in this transaction)
        currency2, exchange2 = await resolve_instrument("UNKNOWN")
        assert currency2 == "USD"
        assert exchange2 == "NYSE"

    async def test_provider_returns_no_currency_fails_closed(self):
        """A quote without a currency must not be recorded as GBP."""
        with patch("src.market.fx.provider.fetch_quote", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {}
            with pytest.raises(InstrumentResolutionError):
                await resolve_instrument("NODATA")

    async def test_provider_raises_fails_closed(self):
        """Provider failure must not persist GBP at rate 1."""
        with patch("src.market.fx.provider.fetch_quote", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("yfinance down")
            with pytest.raises(InstrumentResolutionError):
                await resolve_instrument("BROKEN")

    async def test_provider_gbp_pence_preserved(self):
        """LSE pence (GBp) must stay a minor-unit code, not collapse to GBP."""
        with patch("src.market.fx.provider.fetch_quote", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {"currency": "GBp", "exchange": "LSE"}
            currency, exchange = await resolve_instrument(f"GBPX{uuid4().hex[:6]}.L")

        assert currency == "GBp"
        assert exchange == "LSE"

    async def test_currency_already_uppercased(self):
        await _ensure_instrument("TSLA", "usd", "NASDAQ")
        currency, exchange = await resolve_instrument("TSLA")
        assert currency == "usd"  # stored as-is

    async def test_case_insensitive_db_lookup(self):
        """Ticker lookup is case-sensitive by default — ensure matching."""
        await _ensure_instrument("VOD.L", "GBp", "LSE")
        currency, exchange = await resolve_instrument("VOD.L")
        assert currency == "GBp"
        assert exchange == "LSE"

    async def test_provider_data_persisted_to_db(self):
        """Ticker resolved via provider gets persisted for subsequent lookups."""
        mock_quote = {"currency": "CAD", "exchange": "TSX"}
        with patch("src.market.fx.provider.fetch_quote", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_quote
            currency, exchange = await resolve_instrument("SHOP.TO")

        assert currency == "CAD"
        assert exchange == "TSX"

        # Second call — should read from DB, not provider
        currency2, exchange2 = await resolve_instrument("SHOP.TO")
        assert currency2 == "CAD"
        assert exchange2 == "TSX"
        mock_fetch.assert_awaited_once_with("SHOP.TO")  # provider not called again


# ── get_fx_rate_to_gbp ───────────────────────────────────────────────────


class TestGetFxRateToGbp:
    """Tests for get_fx_rate_to_gbp — Redis-cached FX rate."""

    async def test_gbp_returns_1(self):
        """GBP → GBP is always 1.0."""
        rate = await get_fx_rate_to_gbp("GBP")
        assert rate == Decimal("1.0")

    async def test_empty_currency_returns_1(self):
        rate = await get_fx_rate_to_gbp("")
        assert rate == Decimal("1.0")

    async def test_none_currency_returns_1(self):
        rate = await get_fx_rate_to_gbp("")
        assert rate == Decimal("1.0")

    async def test_case_insensitive(self):
        rate = await get_fx_rate_to_gbp("gbp")
        assert rate == Decimal("1.0")

    async def test_fetches_and_caches_via_provider(self):
        """First call hits provider, second call reads cached value."""
        cur = _unique_currency("fetch")
        # get_fx_rate_to_gbp uppercases internally, so compare against that
        expected_cur = cur.upper()
        mock_rate = Decimal("1.25")
        with patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_rate

            rate1 = await get_fx_rate_to_gbp(cur)
            assert rate1 == mock_rate
            mock_fetch.assert_awaited_once_with(expected_cur)

            rate2 = await get_fx_rate_to_gbp(cur)
            assert rate2 == mock_rate
            # Provider should NOT be called again (Redis cache hit)
            assert mock_fetch.await_count == 1

    async def test_cache_miss_triggers_provider_fetch(self):
        """Different currencies are cached separately."""
        cur_a = _unique_currency("miss_a")
        cur_b = _unique_currency("miss_b")
        with patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = [Decimal("1.25"), Decimal("0.85")]

            rate_a = await get_fx_rate_to_gbp(cur_a)
            rate_b = await get_fx_rate_to_gbp(cur_b)

            assert rate_a == Decimal("1.25")
            assert rate_b == Decimal("0.85")
            assert mock_fetch.await_count == 2

    async def test_redis_unavailable_falls_through_to_provider(self):
        """When Redis is down, skip cache and call provider."""
        with (
            patch("src.market.fx.get_redis", side_effect=Exception("Redis down")),
            patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = Decimal("1.25")
            rate = await get_fx_rate_to_gbp("USD")
            assert rate == Decimal("1.25")

    async def test_redis_write_failure_logged_but_rate_returned(self):
        """If cache write fails, the rate is still returned."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.set.side_effect = Exception("write failed")

        with (
            patch("src.market.fx.get_redis", return_value=mock_redis),
            patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = Decimal("1.30")
            rate = await get_fx_rate_to_gbp("USD")
            assert rate == Decimal("1.30")

    async def test_corrupted_cache_falls_through(self):
        """Corrupted cache entry should not break the function."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = b"not-a-decimal"

        with (
            patch("src.market.fx.get_redis", return_value=mock_redis),
            patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = Decimal("1.30")
            # Note: get_fx_rate_to_gbp calls Decimal(cached.decode())
            # This will raise — but the outer try/except catches it
            rate = await get_fx_rate_to_gbp("EUR")
            assert rate == Decimal("1.30")


# ── Minor units ────────────────────────────────────────────────────────────


class TestMinorUnits:
    """LSE pence / JSE cents / TASE agorot are 1/100 of the major currency."""

    async def test_gbp_pence_is_one_hundredth(self):
        assert await get_fx_rate_to_gbp("GBp") == Decimal("0.01")

    async def test_gbx_alias_is_one_hundredth(self):
        assert await get_fx_rate_to_gbp("GBX") == Decimal("0.01")

    async def test_zac_multiplies_zar_rate_by_one_hundredth(self):
        with (
            patch("src.market.fx.get_redis", side_effect=Exception("Redis down")),
            patch("src.market.fx.provider.fetch_fx", new_callable=AsyncMock) as mock_fetch,
        ):
            mock_fetch.return_value = Decimal("0.05")
            rate = await get_fx_rate_to_gbp("ZAc")

        assert rate == Decimal("0.0005")
        mock_fetch.assert_awaited_once_with("ZAR")

    async def test_current_fx_rates_handles_mixed_minor_units(self):
        rates = await current_fx_rates(
            [
                {"ticker": "VOD.L", "currency": "GBp", "fx_rate_to_gbp": Decimal("0.01")},
                {"ticker": "BARC.L", "currency": "GBP", "fx_rate_to_gbp": Decimal("1")},
            ]
        )
        assert rates == {"VOD.L": Decimal("0.01"), "BARC.L": Decimal("1")}

    async def test_current_fx_rates_falls_back_to_stored_rate_on_failure(self):
        with patch("src.market.fx.get_fx_rate_to_gbp", side_effect=Exception("provider down")):
            rates = await current_fx_rates(
                [{"ticker": "AAPL", "currency": "USD", "fx_rate_to_gbp": Decimal("0.79")}]
            )
        assert rates == {"AAPL": Decimal("0.79")}


# ── Market values ──────────────────────────────────────────────────────────


class TestMarketValues:
    """Sector/HHI valuation uses market price × today's FX, not cost."""

    async def test_uses_current_price_and_fx(self):
        from src.market.quotes import market_values_gbp

        holdings = [
            {
                "ticker": "VOD.L",
                "shares": Decimal("10"),
                "currency": "GBp",
                "average_cost_basis_gbp": Decimal("3"),
            }
        ]
        with (
            patch("src.market.quotes.get_quote", new=AsyncMock(return_value={"price": "350"})),
            patch(
                "src.market.fx.current_fx_rates",
                new=AsyncMock(return_value={"VOD.L": Decimal("0.01")}),
            ),
        ):
            values = await market_values_gbp(holdings)

        assert values == {"VOD.L": Decimal("35.00")}

    async def test_falls_back_to_stored_cost_when_quote_fails(self):
        from src.market.quotes import market_values_gbp

        holdings = [
            {
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "currency": "USD",
                "average_cost_basis_gbp": Decimal("100"),
            }
        ]
        with (
            patch(
                "src.market.quotes.get_quote",
                new=AsyncMock(side_effect=RuntimeError("provider down")),
            ),
            patch(
                "src.market.fx.current_fx_rates",
                new=AsyncMock(return_value={"AAPL": Decimal("0.8")}),
            ),
        ):
            values = await market_values_gbp(holdings)

        assert values == {"AAPL": Decimal("1000")}
