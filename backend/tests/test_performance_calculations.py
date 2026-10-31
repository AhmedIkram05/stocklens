"""
Tests for performance/calculations.py — pure portfolio computation functions.

These functions take all data as arguments (no DB/Redis access), making them
straightforward to unit-test in isolation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.performance.calculations import (
    BenchmarkComparisonResponse,
    HoldingPerformance,
    PortfolioPerformanceResponse,
    _compute_twr,
    _get_closest_price,
    _sorted_price_dates,
    align_daily_return_series,
    compute_benchmark_comparison,
    compute_holding_performance,
    compute_portfolio_performance,
)


class TestComputeHoldingPerformance:
    """Tests for compute_holding_performance — single-holding metrics."""

    def test_basic_metrics(self):
        hp = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("100"),
            avg_cost_basis=Decimal("150"),
            current_price=Decimal("200"),
            previous_close=Decimal("195"),
            total_portfolio_value=Decimal("50000"),
        )
        assert isinstance(hp, HoldingPerformance)
        assert hp.ticker == "AAPL"
        assert hp.shares == 100
        assert hp.cost_basis == Decimal("15000")  # 100 * 150
        assert hp.market_value == Decimal("20000")  # 100 * 200
        assert hp.unrealised_pl == Decimal("5000")  # 20000 - 15000
        # Allow 3 decimal places of precision for the divmod calculation
        assert hp.unrealised_pl_pct == pytest.approx(Decimal("33.3333"), rel=Decimal("1e-3"))
        assert hp.day_change == Decimal("500")  # 100 * (200 - 195)
        # (200-195)/195 * 100 ≈ 2.5641 — allow 3 dp
        assert hp.day_change_pct == pytest.approx(Decimal("2.5641"), rel=Decimal("1e-3"))

    def test_no_current_price(self):
        hp = compute_holding_performance(
            ticker="TSLA",
            shares=Decimal("50"),
            avg_cost_basis=Decimal("200"),
            current_price=None,
            previous_close=None,
            total_portfolio_value=Decimal("50000"),
        )
        assert hp.market_value is None
        assert hp.unrealised_pl is None
        assert hp.unrealised_pl_pct is None
        assert hp.day_change is None
        assert hp.day_change_pct is None
        assert hp.portfolio_weight_pct is None

    def test_zero_cost_basis(self):
        """Zero-cost-basis holdings (transfers, DRIP) — P&L% is undefined."""
        hp = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("0"),
            current_price=Decimal("100"),
            previous_close=Decimal("99"),
            total_portfolio_value=Decimal("10000"),
        )
        assert hp.cost_basis == Decimal("0")
        assert hp.market_value == Decimal("1000")
        assert hp.unrealised_pl == Decimal("1000")
        assert hp.unrealised_pl_pct is None  # undefined for zero cost basis

    def test_no_previous_close(self):
        hp = compute_holding_performance(
            ticker="GOOGL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("100"),
            current_price=Decimal("120"),
            previous_close=None,
            total_portfolio_value=Decimal("5000"),
        )
        assert hp.day_change is None
        assert hp.day_change_pct is None

    def test_with_fx_rate(self):
        """FX rate should convert per-share prices to GBP."""
        hp = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("150"),  # USD
            current_price=Decimal("200"),  # USD
            previous_close=Decimal("195"),  # USD
            total_portfolio_value=Decimal("10000"),
            fx_rate=Decimal("0.75"),  # 1 USD = 0.75 GBP
        )
        # After FX conversion: avg_cost=112.5, curr_price=150, prev_close=146.25
        assert hp.cost_basis == Decimal("1125.0")  # 10 * 150 * 0.75
        assert hp.market_value == Decimal("1500.0")  # 10 * 200 * 0.75
        assert hp.average_cost_basis == Decimal("112.5")

    def test_no_portfolio_weight_when_no_total_value(self):
        hp = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("100"),
            current_price=Decimal("150"),
            previous_close=Decimal("145"),
            total_portfolio_value=None,
        )
        assert hp.portfolio_weight_pct is None


class TestComputePortfolioPerformance:
    """Tests for compute_portfolio_performance — aggregate portfolio metrics."""

    def test_empty_holdings(self):
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Empty",
            holdings_data=[],
            transactions=[],
            cash_flows=[],
            price_map={},
            enable_twr=False,
        )
        assert isinstance(result, PortfolioPerformanceResponse)
        assert result.total_market_value == Decimal("0")
        assert result.total_cost_basis == Decimal("0")
        assert result.holdings == []
        assert result.data_quality == "complete"  # 0/0 holdings with prices = complete
        assert result.fx_unknown_tickers == []

    def test_fx_unknown_holdings_surfaced(self):
        """Non-GBP holdings valued at rate 1 must surface as a data-quality signal.

        A USD holding whose FX lookup failed (or was defaulted to the column
        value 1.0) is silently summed as if USD = GBP — the response now names
        the affected tickers instead of hiding the degrade.
        """
        holdings = [
            {
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "average_cost_basis": Decimal("100"),
                "currency": "USD",
                "fx_rate_to_gbp": Decimal("1.0"),
            },
            {
                "ticker": "VOD",
                "shares": Decimal("10"),
                "average_cost_basis": Decimal("100"),
                "currency": "GBP",
                "fx_rate_to_gbp": Decimal("1.0"),
            },
            {
                "ticker": "SAP",
                "shares": Decimal("10"),
                "average_cost_basis": Decimal("100"),
                "currency": "EUR",
                "fx_rate_to_gbp": Decimal("0.85"),
            },
            {
                "ticker": "MSFT",
                "shares": Decimal("10"),
                "average_cost_basis": Decimal("100"),
                "currency": "USD",
                "fx_rate_to_gbp": Decimal("1.0"),
            },
        ]
        price_map = {
            t: {date(2024, 12, 31): Decimal("120")} for t in ("AAPL", "VOD", "SAP", "MSFT")
        }
        # fx_rates omits MSFT entirely (the queries.py `or Decimal(1)` default fires)
        fx_rates = {"AAPL": Decimal("1.0"), "VOD": Decimal("1.0"), "SAP": Decimal("0.85")}
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="FX",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
            fx_rates=fx_rates,
        )
        assert result.fx_unknown_tickers == ["AAPL", "MSFT"], (
            "USD holdings valued at rate 1 must be flagged; GBP at 1 and EUR at 0.85 must not"
        )

    def test_fx_unknown_absent_when_all_rates_real(self):
        holdings = [
            {
                "ticker": "SAP",
                "shares": Decimal("10"),
                "average_cost_basis": Decimal("100"),
                "currency": "EUR",
                "fx_rate_to_gbp": Decimal("0.85"),
            },
        ]
        price_map = {"SAP": {date(2024, 12, 31): Decimal("120")}}
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="FX-clean",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
            fx_rates={"SAP": Decimal("0.85")},
        )
        assert result.fx_unknown_tickers == []

    def test_single_holding_with_profit(self):
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("100"), "average_cost_basis": Decimal("150")},
        ]
        price_map = {
            "AAPL": {
                date(2024, 1, 1): Decimal("140"),
                date(2024, 12, 31): Decimal("200"),
            },
        }
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Test",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
        )
        assert result.total_market_value == Decimal("20000")
        assert result.total_cost_basis == Decimal("15000")
        assert result.total_unrealised_pl == Decimal("5000")

    def test_live_quotes_override_price_map(self):
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")},
        ]
        price_map = {
            "AAPL": {date(2024, 1, 1): Decimal("90"), date(2024, 12, 31): Decimal("120")},
        }
        live_quotes = {"AAPL": (Decimal("150"), Decimal("145"))}

        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Test",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
            live_quotes=live_quotes,
        )
        assert result.total_market_value == Decimal("1500")  # 10 * 150 (live quote)

    def test_free_cash_balance(self):
        """Free cash balance = deposits - net invested."""
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")}
        ]
        price_map = {"AAPL": {date(2024, 12, 31): Decimal("150")}}
        transactions = [
            {
                "ticker": "AAPL",
                "shares": Decimal("10"),
                "price_per_share": Decimal("100"),
                "total_amount": Decimal("1000"),
                "total_amount_gbp": Decimal("1000"),
                "type": "BUY",
                "date": date(2024, 6, 1),
            },
        ]
        cash_flows = [{"amount": Decimal("2000"), "created_at": date(2024, 1, 1)}]

        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Test",
            holdings_data=holdings,
            transactions=transactions,
            cash_flows=cash_flows,
            price_map=price_map,
            enable_twr=False,
        )
        assert result.free_cash_balance == Decimal("1000")  # 2000 - 1000

    def test_partial_data_quality(self):
        """Data quality is 'partial' when some holdings lack prices."""
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")},
            {"ticker": "UNKNOWN", "shares": Decimal("5"), "average_cost_basis": Decimal("50")},
        ]
        price_map = {
            "AAPL": {date(2024, 12, 31): Decimal("150")},
            # UNKNOWN has no prices
        }

        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Partial",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
        )
        assert result.data_quality == "partial"

    def test_twr_disabled(self):
        """TWR fields should be None when enable_twr=False."""
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")}
        ]
        price_map = {"AAPL": {date(2024, 12, 31): Decimal("150")}}

        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Test",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            enable_twr=False,
        )
        assert result.twr is None
        assert result.twr_annualised is None


class TestComputeBenchmarkComparison:
    """Tests for compute_benchmark_comparison — benchmark comparison metrics."""

    def test_basic_comparison(self):
        port_returns = [Decimal("0.01"), Decimal("0.02"), Decimal("-0.01"), Decimal("0.015")]
        bench_returns = [Decimal("0.008"), Decimal("0.015"), Decimal("-0.005"), Decimal("0.01")]

        result = compute_benchmark_comparison(
            portfolio_id="p1",
            portfolio_twr=Decimal("0.035"),
            benchmark_ticker="SPY",
            portfolio_daily_returns=port_returns,
            benchmark_daily_returns=bench_returns,
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert isinstance(result, BenchmarkComparisonResponse)
        assert result.portfolio_id == "p1"
        assert result.benchmark_ticker == "SPY"
        assert result.portfolio_return == Decimal("0.035")

    def test_no_portfolio_twr(self):
        result = compute_benchmark_comparison(
            portfolio_id="p1",
            portfolio_twr=None,
            benchmark_ticker="SPY",
            portfolio_daily_returns=[],
            benchmark_daily_returns=[],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.portfolio_return is None
        assert result.excess_return_alpha is None

    def test_empty_returns(self):
        result = compute_benchmark_comparison(
            portfolio_id="p1",
            portfolio_twr=Decimal("0"),
            benchmark_ticker="SPY",
            portfolio_daily_returns=[],
            benchmark_daily_returns=[],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.tracking_error is None
        assert result.information_ratio is None
        assert result.daily_returns_count == 0


class TestFlatHoldingDayChange:
    """M1 regression: a 0% day change is a real weight, not a falsy Decimal."""

    def test_flat_holding_dilutes_weighted_average(self):
        # Two equal start-of-day holdings: A +2%, B flat. The weighted average
        # must be 1.0% — the pre-fix truthiness check dropped B (Decimal(0) is
        # falsy) and returned 2.0%.
        price_map = {
            "AAPL": {date(2024, 5, 1): Decimal("100"), date(2024, 5, 2): Decimal("102")},
            "MSFT": {date(2024, 5, 1): Decimal("100"), date(2024, 5, 2): Decimal("100")},
        }
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("100"), "average_cost_basis": Decimal("90")},
            {"ticker": "MSFT", "shares": Decimal("100"), "average_cost_basis": Decimal("90")},
        ]
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="P",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 2),
        )
        assert result.day_change_pct == pytest.approx(Decimal("1.0"), abs=Decimal("1e-9"))


class TestAlignDailyReturnSeries:
    """M2 regression: portfolio and benchmark returns must pair by date, not index."""

    def test_pairs_on_common_dates_only(self):
        # Portfolio calendar has an extra ticker-only day (2024-01-03) and the
        # benchmark is missing 2024-01-04. Positional pairing would difference
        # different days; the date join must drop non-common days.
        portfolio_dates = [
            date(2024, 1, 1),
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 4),
            date(2024, 1, 5),
        ]
        portfolio_returns = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.04")]
        benchmark_dates = [
            date(2024, 1, 1),
            date(2024, 1, 2),
            date(2024, 1, 4),
            date(2024, 1, 5),
        ]
        benchmark_returns = [Decimal("0.005"), Decimal("0.007"), Decimal("0.009")]

        common, p_aligned, b_aligned = align_daily_return_series(
            portfolio_dates, portfolio_returns, benchmark_dates, benchmark_returns
        )
        # returns[i] belongs to dates[i+1]; common end-dates are 01-02, 01-04, 01-05
        assert common == [date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 5)]
        assert p_aligned == [Decimal("0.01"), Decimal("0.03"), Decimal("0.04")]
        assert b_aligned == [Decimal("0.005"), Decimal("0.007"), Decimal("0.009")]


class TestGetClosestPriceBisect:
    """M9 regression: bisect lookup must equal the naive all-dates scan."""

    @staticmethod
    def _naive(price_map, ticker, target):
        ticker_prices = price_map[ticker]
        available = [d for d in ticker_prices if d <= target]
        return ticker_prices[max(available)] if available else None

    def test_matches_naive_scan(self):
        # Unsorted insertion order on purpose — the index must sort it.
        price_map = {
            "AAPL": {date(2024, 1, d): Decimal(d) for d in (15, 3, 20, 7, 1, 11, 28, 5, 23, 9)}
        }
        sorted_dates = _sorted_price_dates(price_map)
        for target in (
            date(2023, 12, 31),
            date(2024, 1, 1),
            date(2024, 1, 10),
            date(2024, 1, 16),
            date(2024, 1, 28),
            date(2025, 6, 1),
        ):
            assert _get_closest_price(price_map, "AAPL", target, sorted_dates) == self._naive(
                price_map, "AAPL", target
            )
            # Default (no pre-sorted index) path must also match.
            assert _get_closest_price(price_map, "AAPL", target) == self._naive(
                price_map, "AAPL", target
            )

    def test_before_first_date_returns_none(self):
        price_map = {"AAPL": {date(2024, 1, 5): Decimal("100")}}
        sorted_dates = _sorted_price_dates(price_map)
        assert _get_closest_price(price_map, "AAPL", date(2024, 1, 4), sorted_dates) is None

    def test_unknown_ticker_returns_none(self):
        assert _get_closest_price({}, "AAPL", date(2024, 1, 5)) is None


class TestDegenerateQuoteDayChange:
    """A zero-priced live quote must not divide by zero."""

    def test_zero_price_quote_degrades_without_error(self):
        # price 0 vs previous close 100 → day_change_pct == -100, so the
        # start-of-day divisor (1 + pct/100) is 0. The weighted day-change must
        # degrade (pct None) instead of raising ZeroDivisionError.
        holdings = [
            {"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")}
        ]
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Z",
            holdings_data=holdings,
            transactions=[],
            cash_flows=[],
            price_map={"AAPL": {date(2024, 12, 31): Decimal("100")}},
            enable_twr=False,
            live_quotes={"AAPL": (Decimal("0"), Decimal("100"))},
        )
        assert result.total_market_value == Decimal("0")
        assert result.day_change == Decimal("-1000")  # 10 * (0 - 100)
        assert result.day_change_pct is None


class TestPreviousCloseGap:
    """A stale/holey feed must not report a multi-day move as a day change."""

    _HOLDINGS = [{"ticker": "AAPL", "shares": Decimal("10"), "average_cost_basis": Decimal("100")}]

    def test_gap_larger_than_threshold_leaves_day_change_none(self):
        price_map = {
            "AAPL": {
                date(2024, 1, 2): Decimal("100"),
                date(2024, 1, 20): Decimal("110"),  # 18-day hole
            }
        }
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Stale",
            holdings_data=self._HOLDINGS,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 20),
            enable_twr=False,
        )
        hp = result.holdings[0]
        assert hp.current_price == Decimal("110")
        assert hp.day_change is None
        assert hp.day_change_pct is None

    def test_consecutive_sessions_keep_day_change(self):
        price_map = {
            "AAPL": {
                date(2024, 1, 2): Decimal("100"),
                date(2024, 1, 3): Decimal("110"),
            }
        }
        result = compute_portfolio_performance(
            portfolio_id="p1",
            portfolio_name="Fresh",
            holdings_data=self._HOLDINGS,
            transactions=[],
            cash_flows=[],
            price_map=price_map,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            enable_twr=False,
        )
        hp = result.holdings[0]
        assert hp.day_change == Decimal("100")  # 10 * (110 - 100)


class TestTWRMissingPrices:
    """A held-but-unpriced position must not silently corrupt TWR."""

    def test_subperiod_with_unpriced_holding_is_skipped(self):
        # NEWCO is bought on 2024-06-01 but its first price is only 2024-12-31.
        # Valuing it at £0 on 2024-06-01 would fabricate a ~+54.5% sub-period
        # return; the period must be skipped so TWR only links priced spans.
        transactions = [
            {
                "ticker": "AAPL",
                "type": "BUY",
                "shares": Decimal("100"),
                "date": date(2023, 1, 1),
                "total_amount_gbp": Decimal("10000"),
            },
            {
                "ticker": "NEWCO",
                "type": "BUY",
                "shares": Decimal("100"),
                "date": date(2024, 6, 1),
                "total_amount_gbp": Decimal("5000"),
            },
        ]
        price_map = {
            "AAPL": {
                date(2024, 1, 1): Decimal("100"),
                date(2024, 6, 1): Decimal("110"),
                date(2024, 12, 31): Decimal("120"),
            },
            "NEWCO": {date(2024, 12, 31): Decimal("50")},
        }
        twr, _ = _compute_twr(transactions, [], price_map, date(2024, 1, 1), date(2024, 12, 31))
        # Only the fully-priced AAPL sub-period links: 11000/10000 - 1 = 10%.
        assert twr == pytest.approx(Decimal("0.1"), abs=Decimal("1e-9"))

    def test_all_subperiods_unpriced_returns_none(self):
        transactions = [
            {
                "ticker": "NEWCO",
                "type": "BUY",
                "shares": Decimal("100"),
                "date": date(2023, 1, 1),
                "total_amount_gbp": Decimal("5000"),
            },
        ]
        # No price at/before either boundary → every sub-period is invalid.
        price_map = {"NEWCO": {date(2024, 12, 31): Decimal("50")}}
        twr, twr_annualised = _compute_twr(
            transactions, [], price_map, date(2024, 1, 1), date(2024, 12, 31)
        )
        assert twr is None
        assert twr_annualised is None
