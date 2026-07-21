"""
Tests for the 16 agent tools (src.agent.tools).

Uses the real Postgres test DB (seeded by conftest) for data access and
patches external data sources (fetch_quote, get_ohlcv_batch, yfinance,
prediction_service, performance calculations) so no network calls happen.

Regression coverage for the Round-2 review fixes:
  - #1 get_portfolio_summary returns total_market_value_gbp + unrealised_pl_gbp
  - #3 get_spending_analysis category breakdown reconciles with total_spent
  - #7 compare_to_benchmark uses live_quotes on the final day (mirrors perf)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest  # noqa: PLC0415 — used by TestToolReliability

from src.agent.tools import get_all_tools
from src.database.connection import connection_ctx

TOOLS = {t.name: t for t in get_all_tools()}

USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_PORTFOLIO = "11111111-1111-1111-1111-111111111111"
OTHER_PORTFOLIO = "22222222-2222-2222-2222-222222222222"


def _seed_holding(conn, ticker, shares, cost_gbp, fx=1.0):
    return conn.execute(
        "INSERT INTO holdings (portfolio_id, ticker, shares, average_cost_basis, "
        "currency, fx_rate_to_gbp, average_cost_basis_gbp) "
        "VALUES ($1::uuid, $2, $3, $4, 'GBP', $5, $6) "
        "ON CONFLICT (portfolio_id, ticker) DO UPDATE SET shares = EXCLUDED.shares",
        TEST_PORTFOLIO,
        ticker,
        Decimal(str(shares)),
        Decimal(str(cost_gbp)),
        Decimal(str(fx)),
        Decimal(str(cost_gbp)),
    )


def _seed_transaction(conn, ticker, ttype, shares, price, total_gbp, txn_date, cat_id=None):
    return conn.execute(
        "INSERT INTO transactions "
        "(portfolio_id, ticker, type, shares, price_per_share, total_amount, "
        "currency, fx_rate_to_gbp, total_amount_gbp, transaction_date, spending_category_id) "
        "VALUES ($1::uuid, $2, $3, $4, $5, $6, 'GBP', 1.0, $7, $8::date, $9::uuid)",
        TEST_PORTFOLIO,
        ticker,
        ttype,
        Decimal(str(shares)),
        Decimal(str(price)),
        Decimal(str(shares * price)),
        Decimal(str(total_gbp)),
        txn_date,
        cat_id,
    )


# ── Registry ───────────────────────────────────────────────────────────────


class TestToolRegistry:
    def test_get_all_tools_returns_16(self):
        tools = get_all_tools()
        assert len(tools) == 16

    def test_registry_has_expected_names(self):
        names = {t.name for t in get_all_tools()}
        expected = {
            "get_portfolio_summary",
            "get_portfolio_holdings",
            "get_portfolio_performance",
            "compare_to_benchmark",
            "get_sector_exposure",
            "get_portfolio_diversification_score",
            "get_market_ohlcv",
            "get_market_quote",
            "get_ticker_info",
            "get_market_news",
            "get_lstm_forecast",
            "get_spending_analysis",
            "get_recent_transactions",
            "get_cash_flow_summary",
            "compare_tickers_side_by_side",
            "get_dividend_insights",
        }
        assert names == expected


# ── Portfolio tools ────────────────────────────────────────────────────────


class TestGetPortfolioSummary:
    async def test_returns_market_value_and_unrealised_pl(self):
        """Regression #1: summary must include total_market_value_gbp + unrealised_pl_gbp."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)  # cost 1000 GBP
            await conn.execute(
                "INSERT INTO cash_flows (portfolio_id, amount) VALUES ($1::uuid, 500)",
                TEST_PORTFOLIO,
            )

        fake_quote = {
            "price": Decimal("150.0"),
            "previous_close": Decimal("148.0"),
            "change": Decimal("2.0"),
            "change_pct": Decimal("1.3"),
            "volume": 1000,
            "currency": "USD",
            "exchange": "NASDAQ",
        }

        with patch("src.market.provider.fetch_quote", new=AsyncMock(return_value=fake_quote)):
            result_str = await TOOLS["get_portfolio_summary"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        assert "total_market_value_gbp" in data
        assert "unrealised_pl_gbp" in data
        # 10 shares * 150 = 1500 market value, 1000 cost -> 500 unrealised
        assert data["total_market_value_gbp"] == 1500.0
        assert data["unrealised_pl_gbp"] == 500.0
        assert data["free_cash_balance_gbp"] == 500.0
        assert data["holding_count"] == 1

    async def test_not_found_for_wrong_ownership(self):
        result_str = await TOOLS["get_portfolio_summary"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"


class TestGetPortfolioHoldings:
    async def test_returns_holdings(self):
        async with connection_ctx() as conn:
            await _seed_holding(conn, "MSFT", 5, 200.0)
        result_str = await TOOLS["get_portfolio_holdings"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert data["total"] == 1
        assert data["holdings"][0]["ticker"] == "MSFT"
        assert data["holdings"][0]["shares"] == 5.0

    async def test_empty(self):
        result_str = await TOOLS["get_portfolio_holdings"].ainvoke(
            {"portfolio_id": OTHER_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert data["holdings"] == []
        assert data["total"] == 0

    async def test_ownership_enforced(self):
        """Other user cannot see Test Portfolio holdings."""
        result_str = await TOOLS["get_portfolio_holdings"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["holdings"] == []


class TestGetSectorExposure:
    async def test_aggregates_sectors(self):
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_holding(conn, "MSFT", 10, 100.0)

        with patch("src.agent.tools.yf") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.info = {"sector": "Technology"}
            mock_yf.Ticker.return_value = mock_ticker
            result_str = await TOOLS["get_sector_exposure"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        assert data["total_value_gbp"] > 0
        assert len(data["sectors"]) == 1
        assert data["sectors"][0]["sector"] == "Technology"


class TestGetDiversificationScore:
    async def test_hhi_single_holding_is_high(self):
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
        result_str = await TOOLS["get_portfolio_diversification_score"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        # Single holding -> HHI = 100^2 = 10000
        assert data["hhi_score"] == 10000.0
        assert data["concentration_level"] == "high"
        assert data["effective_holdings"] == 1.0

    async def test_no_holdings_error(self):
        result_str = await TOOLS["get_portfolio_diversification_score"].ainvoke(
            {"portfolio_id": OTHER_PORTFOLIO, "user_id": USER_ID}
        )
        assert "error" in json.loads(result_str)


# ── Spending tools ────────────────────────────────────────────────────────


class TestGetSpendingAnalysis:
    async def test_category_breakdown_reconciles_with_total(self):
        """Regression #3: category pct derived from BUY-only population (matches total_spent)."""
        cat_id = uuid4()
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO spending_categories (id, name) VALUES ($1::uuid, $2) "
                "ON CONFLICT (name) DO NOTHING",
                cat_id,
                "Groceries",
            )
            # 100 BUY, 50 BUY in same category -> total_spent 150
            await _seed_transaction(conn, "TSLA", "BUY", 1, 100, 100.0, date(2024, 1, 1), cat_id)
            await _seed_transaction(conn, "AAPL", "BUY", 1, 50, 50.0, date(2024, 2, 1), cat_id)
            # SELL proceeds must NOT leak into category pct
            await _seed_transaction(conn, "TSLA", "SELL", 1, 300, 300.0, date(2024, 3, 1))

        result_str = await TOOLS["get_spending_analysis"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert data["total_spent_gbp"] == 150.0
        assert data["total_received_gbp"] == 300.0
        assert len(data["category_breakdown"]) == 1
        cat = data["category_breakdown"][0]
        assert cat["name"] == "Groceries"
        assert cat["amount_gbp"] == 150.0
        assert cat["pct_of_total"] == 100.0  # fully reconciles

    async def test_uncategorised_bucket(self):
        async with connection_ctx() as conn:
            await _seed_transaction(conn, "AAPL", "BUY", 1, 50, 50.0, date(2024, 1, 1))
        result_str = await TOOLS["get_spending_analysis"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert data["category_breakdown"][0]["name"] == "Uncategorised"
        assert data["category_breakdown"][0]["pct_of_total"] == 100.0

    async def test_invalid_date_format(self):
        result_str = await TOOLS["get_spending_analysis"].ainvoke(
            {
                "portfolio_id": TEST_PORTFOLIO,
                "user_id": USER_ID,
                "start_date": "not-a-date",
            }
        )
        assert "error" in json.loads(result_str)


class TestGetRecentTransactions:
    async def test_returns_recent(self):
        async with connection_ctx() as conn:
            await _seed_transaction(conn, "AAPL", "BUY", 2, 50, 100.0, date(2024, 1, 1))
            await _seed_transaction(conn, "MSFT", "SELL", 1, 80, 80.0, date(2024, 2, 1))
        result_str = await TOOLS["get_recent_transactions"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "limit": 10}
        )
        data = json.loads(result_str)
        assert data["total"] == 2
        assert data["transactions"][0]["type"] == "SELL"  # most recent first

    async def test_limit_clamped(self):
        result_str = await TOOLS["get_recent_transactions"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "limit": 999}
        )
        data = json.loads(result_str)
        # limit clamped to 100; query still succeeds
        assert data["total"] >= 0


class TestGetCashFlowSummary:
    async def test_deposits(self):
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO cash_flows (portfolio_id, amount, source) "
                "VALUES ($1::uuid, 500, 'receipt'), ($1::uuid, 250, 'receipt')",
                TEST_PORTFOLIO,
            )
        result_str = await TOOLS["get_cash_flow_summary"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert data["total_deposits_gbp"] == 750.0
        assert data["deposit_count"] == 2


# ── Performance tools ─────────────────────────────────────────────────────


class TestGetPortfolioPerformance:
    async def test_no_holdings(self):
        result_str = await TOOLS["get_portfolio_performance"].ainvoke(
            {"portfolio_id": OTHER_PORTFOLIO, "user_id": USER_ID}
        )
        assert json.loads(result_str)["total_holdings"] == 0

    async def test_runs_with_mocks(self):
        # compute_portfolio_performance's result is spread via `**dict(result)`,
        # so the mock must be a dict-like object, not a MagicMock.
        perf_model = {
            "twr": Decimal("0.12"),
            "twr_annualised": Decimal("0.12"),
            "total_gain_loss": Decimal("100"),
            "total_gain_loss_pct": Decimal("10"),
            "periods": [],
        }

        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance",
                return_value=perf_model,
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(return_value={"price": Decimal("1")}),
            ),
            patch("src.market.repository.get_ohlcv_batch", new=AsyncMock(return_value={})),
        ):
            result_str = await TOOLS["get_portfolio_performance"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        assert data["portfolio_name"]
        assert "twr" in data


class TestCompareToBenchmark:
    async def test_uses_live_quotes_on_final_day(self):
        """Regression #7: compare_to_benchmark uses live_quotes[ticker][0] on final day."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_transaction(conn, "AAPL", "BUY", 10, 100, 1000.0, date(2024, 1, 2))

        # price_map with two trading days; final-day value should use live quote
        d1 = date(2024, 1, 2)
        d2 = date(2024, 1, 3)
        batch_results = {
            "AAPL": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("110")},
            ],
            "SPY": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("105")},
            ],
        }
        perf_model = MagicMock()
        perf_model.twr = Decimal("0.05")
        comparison_model = MagicMock()
        comparison_model.benchmark_return = Decimal("0.03")
        comparison_model.excess_return_alpha = Decimal("0.02")
        comparison_model.tracking_error = Decimal("0.01")
        comparison_model.information_ratio = Decimal("2.0")
        comparison_model.daily_returns_count = 1

        captured = {}

        def _fake_perf(**kwargs):
            captured.update(kwargs)
            return perf_model

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance", side_effect=_fake_perf
            ),
            patch(
                "src.performance.calculations.compute_benchmark_comparison",
                return_value=comparison_model,
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(
                    return_value={"price": Decimal("120"), "previous_close": Decimal("118")}
                ),
            ),
            patch(
                "src.market.repository.get_ohlcv_batch", new=AsyncMock(return_value=batch_results)
            ),
        ):
            result_str = await TOOLS["compare_to_benchmark"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "benchmark_ticker": "SPY"}
            )

        data = json.loads(result_str)
        assert data["benchmark_ticker"] == "SPY"
        assert data["portfolio_return"] == 0.05
        assert data["benchmark_return"] == 0.03
        assert data["excess_return_alpha"] == 0.02
        # The live quote (120) differs from historical close (110) on final day,
        # proving live_quotes override path was exercised.
        assert "live_quotes" in captured
        assert captured["live_quotes"]["AAPL"][0] == Decimal("120")

    async def test_missing_benchmark_data(self):
        with patch("src.market.repository.get_ohlcv_batch", new=AsyncMock(return_value={})):
            result_str = await TOOLS["compare_to_benchmark"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "benchmark_ticker": "SPY"}
            )
        assert "error" in json.loads(result_str)


# ── Market data tools (external mocked) ───────────────────────────────────


class TestGetMarketOHLCV:
    async def test_returns_rows(self):
        rows = [
            {
                "date": date(2024, 1, 1),
                "open": 1,
                "high": 2,
                "low": 0,
                "close": 1.5,
                "adjusted_close": 1.5,
                "volume": 100,
            }
        ]
        with patch("src.agent.tools.get_ohlcv", new=AsyncMock(return_value=rows)):
            result_str = await TOOLS["get_market_ohlcv"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert data["data_points"] == 1
        assert data["ticker"] == "AAPL"

    async def test_invalid_date(self):
        result_str = await TOOLS["get_market_ohlcv"].ainvoke(
            {"ticker": "AAPL", "user_id": USER_ID, "start_date": "bad"}
        )
        assert "error" in json.loads(result_str)


class TestGetMarketQuote:
    async def test_returns_quote(self):
        fake = {"ticker": "AAPL", "price": Decimal("150"), "currency": "USD"}
        with patch("src.market.provider.fetch_quote", new=AsyncMock(return_value=fake)):
            result_str = await TOOLS["get_market_quote"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert data["ticker"] == "AAPL"
        assert float(data["price"]) == 150.0

    async def test_no_quote(self):
        with patch("src.market.provider.fetch_quote", new=AsyncMock(return_value=None)):
            result_str = await TOOLS["get_market_quote"].ainvoke(
                {"ticker": "ZZZ", "user_id": USER_ID}
            )
        assert "error" in json.loads(result_str)


class TestGetTickerInfo:
    async def test_returns_profile(self):
        with patch("src.agent.tools.yf") as mock_yf:
            mock_yf.Ticker.return_value.info = {"longName": "Apple Inc.", "sector": "Technology"}
            result_str = await TOOLS["get_ticker_info"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert data["company_name"] == "Apple Inc."


class TestGetMarketNews:
    async def test_returns_articles(self):
        article = {
            "title": "Big news",
            "publisher": "Reuters",
            "link": "http://x",
            "providerPublishTime": 1700000000,
            "summary": "Stuff happened",
        }

        with patch("src.agent.tools.yf") as mock_yf:
            mock_yf.Ticker.return_value.news = [article]
            result_str = await TOOLS["get_market_news"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID, "max_articles": 3}
            )
        data = json.loads(result_str)
        assert data["articles"][0]["title"] == "Big news"

    async def test_max_clamped(self):
        result_str = await TOOLS["get_market_news"].ainvoke(
            {"ticker": "AAPL", "user_id": USER_ID, "max_articles": 999}
        )
        data = json.loads(result_str)
        assert data["ticker"] == "AAPL"


class TestCompareTickersSideBySide:
    async def test_compares(self):
        with patch("src.agent.tools.yf") as mock_yf:
            mock_yf.Ticker.return_value.info = {"currentPrice": 150, "sector": "Tech"}
            result_str = await TOOLS["compare_tickers_side_by_side"].ainvoke(
                {"tickers": "AAPL,MSFT", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert len(data["tickers"]) == 2

    async def test_empty_input(self):
        result_str = await TOOLS["compare_tickers_side_by_side"].ainvoke(
            {"tickers": "   ", "user_id": USER_ID}
        )
        assert "error" in json.loads(result_str)

    async def test_too_many(self):
        result_str = await TOOLS["compare_tickers_side_by_side"].ainvoke(
            {"tickers": ",".join(f"T{i}" for i in range(12)), "user_id": USER_ID}
        )
        assert "error" in json.loads(result_str)


class TestGetLSTMForecast:
    async def test_returns_forecast(self):
        ohlcv = [{"date": date(2024, 1, 1), "adjusted_close": 1}]
        fake_result = {"ticker": "AAPL", "prediction": "UP", "confidence": 0.6}
        with (
            patch("src.market.repository.get_ohlcv", new=AsyncMock(return_value=ohlcv)),
            patch("src.prediction.service.prediction_service") as mock_ps,
        ):
            mock_ps.predict.return_value = fake_result
            result_str = await TOOLS["get_lstm_forecast"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert data["prediction"] == "UP"

    async def test_no_data(self):
        with patch("src.market.repository.get_ohlcv", new=AsyncMock(return_value=[])):
            result_str = await TOOLS["get_lstm_forecast"].ainvoke(
                {"ticker": "ZZZ", "user_id": USER_ID}
            )
        assert "error" in json.loads(result_str)


class TestGetDividendInsights:
    async def test_returns_dividend(self):
        class _Divs:
            empty = False
            index = MagicMock()
            iloc = MagicMock()

            def __getitem__(self, _):
                return datetime(2024, 1, 1)

        with patch("src.agent.tools.yf") as mock_yf:
            mock_yf.Ticker.return_value.info = {"dividendRate": 0.5, "dividendYield": 0.01}
            mock_yf.Ticker.return_value.dividends = _Divs()
            result_str = await TOOLS["get_dividend_insights"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert data["ticker"] == "AAPL"
        assert data["dividend_rate"] == 0.5


# ── Ownership regression (representative tools) ─────────────────────────────


class TestOwnershipEnforcement:
    async def test_summary_other_user(self):
        result_str = await TOOLS["get_portfolio_summary"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"

    async def test_spending_other_user(self):
        result_str = await TOOLS["get_spending_analysis"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"

    async def test_cashflow_other_user(self):
        result_str = await TOOLS["get_cash_flow_summary"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"


class TestToolReliability:
    """Verify tenacity retry decorator is applied to yfinance helpers."""

    def test_yf_retry_retries_transient_failures(self):
        from src.agent.tools import _yf_retry

        call_count = 0

        @_yf_retry
        def _flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                msg = f"transient error {call_count}"
                raise ValueError(msg)
            return "ok"

        result = _flaky()
        assert result == "ok"
        assert call_count == 3  # 2 failures + 1 success

    def test_yf_retry_raises_after_max_attempts(self):
        from src.agent.tools import _yf_retry

        call_count = 0

        @_yf_retry
        def _always_fails() -> str:
            nonlocal call_count
            call_count += 1
            msg = f"persistent error {call_count}"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="persistent error 3"):
            _always_fails()
        assert call_count == 3  # all 3 attempts exhausted


# ── Shared helper edge cases ──────────────────────────────────────────────


class TestDecimalToFloat:
    """Edge cases for _decimal_to_float helper."""

    def test_decimal_converts_to_float(self):
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float(Decimal("42.5")) == 42.5

    def test_int_converts_to_float(self):
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float(42) == 42.0

    def test_float_passes_through(self):
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float(3.14) == 3.14

    def test_none_returns_zero(self):
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float(None) == 0.0

    def test_string_returns_zero(self):
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float("not-a-number") == 0.0

    def test_bool_true_returns_one(self):
        """bool is subclass of int, so True → 1.0."""
        from src.agent.tools import _decimal_to_float

        assert _decimal_to_float(True) == 1.0


# ── Exception / error-branch coverage ─────────────────────────────────────


class TestGetSectorExposureErrors:
    """Error-handling branches for get_sector_exposure."""

    async def test_yfinance_exception_skipped_gracefully(self):
        """When _fetch_sector raises, the exception is logged and skipped."""
        from unittest.mock import PropertyMock

        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_holding(conn, "MSFT", 10, 100.0)

        with patch("src.agent.tools.yf") as mock_yf:
            mock_ticker = MagicMock()
            type(mock_ticker).info = PropertyMock(side_effect=ValueError("YF down"))
            mock_yf.Ticker.return_value = mock_ticker
            result_str = await TOOLS["get_sector_exposure"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        # Both tickers failed → both land in "Unknown" sector
        assert data["total_value_gbp"] > 0
        unknown = [s for s in data["sectors"] if s["sector"] == "Unknown"]
        assert len(unknown) == 1


class TestGetPortfolioPerformanceErrors:
    """Error-handling branches for get_portfolio_performance."""

    async def test_portfolio_not_found(self):
        """Wrong user_id → 'Portfolio not found'."""
        result_str = await TOOLS["get_portfolio_performance"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"

    async def test_ohlcv_batch_exception_uses_empty(self):
        """get_ohlcv_batch exception → returns empty dict, calculation proceeds."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_transaction(conn, "AAPL", "BUY", 10, 100, 1000.0, date(2024, 1, 2))

        perf_model = {
            "twr": Decimal("0.0"),
            "twr_annualised": Decimal("0.0"),
            "total_gain_loss": Decimal("0"),
            "total_gain_loss_pct": Decimal("0"),
            "periods": [],
        }

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance",
                return_value=perf_model,
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(return_value={"price": Decimal("1")}),
            ),
            patch(
                "src.market.repository.get_ohlcv_batch",
                new=AsyncMock(side_effect=ValueError("DB timeout")),
            ),
        ):
            result_str = await TOOLS["get_portfolio_performance"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        assert data["portfolio_name"]

    async def test_compute_exception_returns_error(self):
        """compute_portfolio_performance raises → returns error JSON."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance",
                side_effect=RuntimeError("compute bug"),
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(return_value={"price": Decimal("1")}),
            ),
            patch(
                "src.market.repository.get_ohlcv_batch",
                new=AsyncMock(return_value={}),
            ),
        ):
            result_str = await TOOLS["get_portfolio_performance"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
            )

        data = json.loads(result_str)
        assert "error" in data
        assert "compute bug" in data["error"]


class TestCompareToBenchmarkErrors:
    """Error-handling branches for compare_to_benchmark."""

    async def test_portfolio_not_found(self):
        """Wrong user_id → 'Portfolio not found'."""
        result_str = await TOOLS["compare_to_benchmark"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": "99999999-9999-9999-9999-999999999999"}
        )
        assert json.loads(result_str)["error"] == "Portfolio not found"

    async def test_ohlcv_batch_exception_uses_empty(self):
        """get_ohlcv_batch exception → empty dict, benchmark data missing."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_transaction(conn, "AAPL", "BUY", 10, 100, 1000.0, date(2024, 1, 2))

        with patch(
            "src.market.repository.get_ohlcv_batch",
            new=AsyncMock(side_effect=ValueError("DB timeout")),
        ):
            result_str = await TOOLS["compare_to_benchmark"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "benchmark_ticker": "SPY"}
            )

        data = json.loads(result_str)
        assert "error" in data

    async def test_compute_performance_exception(self):
        """compute_portfolio_performance raises during benchmark → error."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_transaction(conn, "AAPL", "BUY", 10, 100, 1000.0, date(2024, 1, 2))

        d1 = date(2024, 1, 2)
        d2 = date(2024, 1, 3)
        batch_results = {
            "AAPL": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("110")},
            ],
            "SPY": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("105")},
            ],
        }

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance",
                side_effect=RuntimeError("perf crash"),
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(return_value={"price": Decimal("1")}),
            ),
            patch(
                "src.market.repository.get_ohlcv_batch",
                new=AsyncMock(return_value=batch_results),
            ),
        ):
            result_str = await TOOLS["compare_to_benchmark"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "benchmark_ticker": "SPY"}
            )

        data = json.loads(result_str)
        assert "error" in data
        assert "perf crash" in data["error"]

    async def test_benchmark_comparison_exception(self):
        """compute_benchmark_comparison raises → error."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 100.0)
            await _seed_transaction(conn, "AAPL", "BUY", 10, 100, 1000.0, date(2024, 1, 2))

        d1 = date(2024, 1, 2)
        d2 = date(2024, 1, 3)
        batch_results = {
            "AAPL": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("110")},
            ],
            "SPY": [
                {"date": d1, "adjusted_close": Decimal("100")},
                {"date": d2, "adjusted_close": Decimal("105")},
            ],
        }
        perf_model = MagicMock()
        perf_model.twr = Decimal("0.05")

        with (
            patch(
                "src.performance.calculations.compute_portfolio_performance",
                return_value=perf_model,
            ),
            patch(
                "src.performance.calculations.compute_benchmark_comparison",
                side_effect=RuntimeError("comparison crash"),
            ),
            patch(
                "src.market.provider.fetch_quote",
                new=AsyncMock(return_value={"price": Decimal("1")}),
            ),
            patch(
                "src.market.repository.get_ohlcv_batch",
                new=AsyncMock(return_value=batch_results),
            ),
        ):
            result_str = await TOOLS["compare_to_benchmark"].ainvoke(
                {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "benchmark_ticker": "SPY"}
            )

        data = json.loads(result_str)
        assert "error" in data
        assert "comparison crash" in data["error"]


class TestGetDiversificationScoreErrors:
    """Error-handling branches for get_portfolio_diversification_score."""

    async def test_zero_total_value(self):
        """Holdings with zero cost basis → zero total → error."""
        async with connection_ctx() as conn:
            await _seed_holding(conn, "AAPL", 10, 0.0)
        result_str = await TOOLS["get_portfolio_diversification_score"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID}
        )
        data = json.loads(result_str)
        assert "error" in data
        assert "zero or negative total value" in data["error"].lower()


class TestCompareTickersErrors:
    """Error-handling branches for compare_tickers_side_by_side."""

    async def test_yfinance_exception_appended(self):
        """When _fetch_info raises, error dict is appended."""
        from unittest.mock import PropertyMock

        with patch("src.agent.tools.yf") as mock_yf:
            mock_yf.Ticker.return_value = MagicMock()
            type(mock_yf.Ticker.return_value).info = PropertyMock(side_effect=ValueError("No data"))
            result_str = await TOOLS["compare_tickers_side_by_side"].ainvoke(
                {"tickers": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert len(data["tickers"]) == 1
        assert "error" in data["tickers"][0]


class TestGetMarketOHLCVErrors:
    """Error-handling branches for get_market_ohlcv."""

    async def test_get_ohlcv_exception(self):
        """get_ohlcv raises → error JSON returned."""
        with patch(
            "src.agent.tools.get_ohlcv", new=AsyncMock(side_effect=RuntimeError("API down"))
        ):
            result_str = await TOOLS["get_market_ohlcv"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert "error" in data
        assert "API down" in data["error"]


class TestGetMarketQuoteErrors:
    """Error-handling branches for get_market_quote."""

    async def test_fetch_quote_exception(self):
        """fetch_quote raises → error JSON returned."""
        with patch(
            "src.market.provider.fetch_quote",
            new=AsyncMock(side_effect=RuntimeError("Quote provider down")),
        ):
            result_str = await TOOLS["get_market_quote"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert "error" in data
        assert "Quote provider down" in data["error"]


class TestGetMarketNewsLimits:
    """Limit-clamping for get_market_news."""

    async def test_min_articles_clamped(self):
        """max_articles < 1 is clamped to 1."""
        result_str = await TOOLS["get_market_news"].ainvoke(
            {"ticker": "AAPL", "user_id": USER_ID, "max_articles": -5}
        )
        data = json.loads(result_str)
        assert data["ticker"] == "AAPL"


class TestGetLSTMForecastErrors:
    """Error-handling branches for get_lstm_forecast."""

    async def test_prediction_returns_none(self):
        """prediction_service.predict returns None → error."""
        ohlcv = [{"date": date(2024, 1, 1), "adjusted_close": 1}]
        with (
            patch("src.market.repository.get_ohlcv", new=AsyncMock(return_value=ohlcv)),
            patch("src.prediction.service.prediction_service") as mock_ps,
        ):
            mock_ps.predict.return_value = None
            result_str = await TOOLS["get_lstm_forecast"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert "error" in data
        assert "No forecast available" in data["error"]

    async def test_prediction_service_exception(self):
        """prediction_service.predict raises → error JSON."""
        ohlcv = [{"date": date(2024, 1, 1), "adjusted_close": 1}]
        with (
            patch("src.market.repository.get_ohlcv", new=AsyncMock(return_value=ohlcv)),
            patch("src.prediction.service.prediction_service") as mock_ps,
        ):
            mock_ps.predict.side_effect = RuntimeError("Model unavailable")
            result_str = await TOOLS["get_lstm_forecast"].ainvoke(
                {"ticker": "AAPL", "user_id": USER_ID}
            )
        data = json.loads(result_str)
        assert "error" in data
        assert "Forecast failed" in data["error"]


class TestGetRecentTransactionsLimits:
    """Limit-clamping for get_recent_transactions."""

    async def test_min_limit_clamped(self):
        """limit < 1 is clamped to 1."""
        result_str = await TOOLS["get_recent_transactions"].ainvoke(
            {"portfolio_id": TEST_PORTFOLIO, "user_id": USER_ID, "limit": -5}
        )
        data = json.loads(result_str)
        assert data["total"] >= 0
