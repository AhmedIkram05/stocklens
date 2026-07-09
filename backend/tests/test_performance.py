"""
Tests for the portfolio performance module.

Covers pure computation functions (no mocking needed), TWR, benchmark comparison,
and HTTP endpoint integration tests.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

# ──────────────────────────────────────────────────────────────────────
# Holding Performance — pure function tests
# ──────────────────────────────────────────────────────────────────────


class TestHoldingPerformance:
    """Tests for per-holding performance calculations."""

    def test_basic_calculation(self):
        """Basic P&L calculation with all data available."""
        from src.performance.calculations import compute_holding_performance

        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("100"),
            avg_cost_basis=Decimal("150.00"),
            current_price=Decimal("180.00"),
            previous_close=Decimal("178.00"),
            total_portfolio_value=Decimal("18000.00"),
        )
        assert result.ticker == "AAPL"
        assert result.shares == Decimal("100")
        assert result.market_value == Decimal("18000.00")
        assert result.cost_basis == Decimal("15000.00")
        assert result.unrealised_pl == Decimal("3000.00")
        assert result.unrealised_pl_pct == Decimal("20.00")
        assert result.day_change == Decimal("200.00")
        assert result.portfolio_weight_pct == Decimal("100.00")

    def test_missing_price(self):
        """Missing current_price → all price-dependent values are None."""
        from src.performance.calculations import compute_holding_performance

        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("100"),
            avg_cost_basis=Decimal("150.00"),
            current_price=None,
            previous_close=None,
            total_portfolio_value=None,
        )
        assert result.current_price is None
        assert result.market_value is None
        assert result.unrealised_pl is None
        assert result.day_change is None
        assert result.portfolio_weight_pct is None

    def test_zero_cost_basis(self):
        """Zero cost basis → unrealised P&L % is None."""
        from src.performance.calculations import compute_holding_performance

        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("0"),
            current_price=Decimal("180.00"),
            previous_close=Decimal("178.00"),
            total_portfolio_value=Decimal("1800.00"),
        )
        assert result.cost_basis == Decimal("0")
        assert result.market_value == Decimal("1800.00")
        assert result.unrealised_pl_pct is None

    def test_no_previous_close(self):
        """No previous_close → day_change is None."""
        from src.performance.calculations import compute_holding_performance

        result = compute_holding_performance(
            ticker="AAPL",
            shares=Decimal("10"),
            avg_cost_basis=Decimal("150.00"),
            current_price=Decimal("180.00"),
            previous_close=None,
            total_portfolio_value=Decimal("1800.00"),
        )
        assert result.day_change is None
        assert result.day_change_pct is None


# ──────────────────────────────────────────────────────────────────────
# Portfolio Performance — aggregate function tests
# ──────────────────────────────────────────────────────────────────────


class TestPortfolioPerformance:
    """Tests for aggregate portfolio performance computation."""

    def test_single_holding_no_transactions(self):
        """Single holding without any transactions or cash flows."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("100"),
                    "average_cost_basis": Decimal("150.00"),
                },
            ],
            transactions=[],
            cash_flows=[],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("150.00"),
                    date(2024, 6, 30): Decimal("165.00"),
                    date(2024, 12, 31): Decimal("180.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            enable_twr=True,
        )
        assert result.total_market_value == Decimal("18000.00")
        assert result.total_cost_basis == Decimal("15000.00")
        assert result.total_unrealised_pl == Decimal("3000.00")
        assert result.total_holdings == 1
        assert result.free_cash_balance == Decimal("0")
        assert result.data_quality == "complete"
        # No transactions or cash flows → TWR is undefined
        assert result.twr is None

    def test_empty_portfolio(self):
        """Empty portfolio (no holdings) returns zeros but no error."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="empty-id",
            portfolio_name="Empty",
            holdings_data=[],
            transactions=[],
            cash_flows=[],
            price_map={},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert result.total_market_value == Decimal("0")
        assert result.total_cost_basis == Decimal("0")
        assert result.total_holdings == 0
        assert result.holdings == []

    def test_free_cash_balance_computed(self):
        """Free cash = deposits - BUYs + SELLs."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
            ],
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 15),
                },
            ],
            cash_flows=[
                {"amount": Decimal("2000.00"), "created_at": datetime(2024, 6, 15)},
            ],
            price_map={
                "AAPL": {
                    date(2024, 6, 15): Decimal("150.00"),
                    date(2024, 12, 31): Decimal("180.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert result.free_cash_balance == Decimal("500.00")  # 2000 - 1500

    def test_enable_twr_false(self):
        """With enable_twr=False, all TWR fields are None."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
            ],
            transactions=[],
            cash_flows=[],
            price_map={"AAPL": {date(2024, 12, 31): Decimal("180.00")}},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            enable_twr=False,
        )
        assert result.twr is None
        assert result.twr_annualised is None

    def test_live_quotes_override_ohlcv(self):
        """Live quotes override OHLCV prices when provided."""
        from src.performance.calculations import compute_portfolio_performance

        ohlcv_prices = {
            "AAPL": {date(2024, 12, 30): Decimal("190.00"), date(2024, 12, 31): Decimal("195.00")},
        }
        live_quotes = {"AAPL": (Decimal("200.00"), Decimal("195.00"))}

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
            ],
            transactions=[],
            cash_flows=[],
            price_map=ohlcv_prices,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            enable_twr=False,
            live_quotes=live_quotes,
        )
        hp = result.holdings[0]
        assert hp.current_price == 200.0  # Live quote overrides OHLCV 195.00
        assert hp.day_change == 50.0  # (200 - 195) * 10
        assert result.total_market_value == 2000.0
        assert result.data_quality == "complete"

    def test_live_quotes_partial_override(self):
        """Only some tickers have live quotes — missing tickers fall back to OHLCV."""
        from src.performance.calculations import compute_portfolio_performance

        ohlcv_prices = {
            "AAPL": {date(2024, 12, 31): Decimal("195.00")},
            "GOOGL": {date(2024, 12, 31): Decimal("180.00")},
        }
        # Only AAPL has live quote
        live_quotes = {"AAPL": (Decimal("200.00"), Decimal("195.00"))}

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
                {
                    "ticker": "GOOGL",
                    "shares": Decimal("5"),
                    "average_cost_basis": Decimal("170.00"),
                },
            ],
            transactions=[],
            cash_flows=[],
            price_map=ohlcv_prices,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            enable_twr=False,
            live_quotes=live_quotes,
        )
        aapl = [h for h in result.holdings if h.ticker == "AAPL"][0]
        googl = [h for h in result.holdings if h.ticker == "GOOGL"][0]
        assert aapl.current_price == 200.0  # Live
        assert googl.current_price == 180.0  # OHLCV fallback
        assert result.data_quality == "complete"

    def test_partial_price_data(self):
        """Some holdings missing price data → data_quality='partial'."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
                {
                    "ticker": "GOOGL",
                    "shares": Decimal("5"),
                    "average_cost_basis": Decimal("2000.00"),
                },
            ],
            transactions=[],
            cash_flows=[],
            price_map={
                "AAPL": {date(2024, 12, 31): Decimal("180.00")},
                # GOOGL has no prices
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert result.data_quality == "partial"
        # Holding with missing price has None market_value
        googl = [h for h in result.holdings if h.ticker == "GOOGL"][0]
        assert googl.market_value is None
        assert googl.current_price is None

    def test_multiple_holdings_weight(self):
        """Portfolio weights sum to ~100%."""
        from src.performance.calculations import compute_portfolio_performance

        result = compute_portfolio_performance(
            portfolio_id="test-id",
            portfolio_name="Test",
            holdings_data=[
                {
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "average_cost_basis": Decimal("150.00"),
                },
                {"ticker": "MSFT", "shares": Decimal("5"), "average_cost_basis": Decimal("300.00")},
            ],
            transactions=[],
            cash_flows=[],
            price_map={
                "AAPL": {date(2024, 12, 31): Decimal("180.00")},
                "MSFT": {date(2024, 12, 31): Decimal("350.00")},
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        total_weight = sum(h.portfolio_weight_pct or 0 for h in result.holdings)
        assert abs(total_weight - Decimal("100")) < Decimal("0.01")


# ──────────────────────────────────────────────────────────────────────
# TWR — Time-Weighted Return tests
# ──────────────────────────────────────────────────────────────────────


class TestTWR:
    """Tests for Time-Weighted Return calculation."""

    def test_no_transactions(self):
        """No transactions or cash_flows in period → TWR is None."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[],
            cash_flows=[],
            price_map={"AAPL": {date(2024, 1, 2): Decimal("180.00")}},
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is None
        assert ann is None

    def test_single_buy_with_cash_flow(self):
        """Single BUY + matching cash_flow deposit → positive TWR."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 15),
                }
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 6, 15),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("148.00"),
                    date(2024, 6, 15): Decimal("150.00"),
                    date(2024, 12, 31): Decimal("152.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0
        assert twr < Decimal("0.02")

    def test_buy_then_growth(self):
        """BUY then price growth → positive TWR."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 1, 2),
                }
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 1, 2),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("150.00"),
                    date(2024, 1, 2): Decimal("150.00"),
                    date(2024, 6, 30): Decimal("165.00"),
                    date(2024, 12, 31): Decimal("180.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0
        assert abs(twr - Decimal("0.20")) < Decimal("0.02")

    def test_bmv_zero_guard(self):
        """BMV = 0 with cash flow → sub-period return is 0 (not division by zero)."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 15),
                }
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 6, 15),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 6, 14): Decimal("150.00"),
                    date(2024, 6, 15): Decimal("151.00"),
                    date(2024, 6, 16): Decimal("152.00"),
                },
            },
            start_date=date(2024, 6, 14),
            end_date=date(2024, 6, 16),
        )
        assert twr is not None
        assert twr > 0
        assert twr < Decimal("0.01")

    def test_sell_transaction(self):
        """SELL transaction (partial exit) is handled."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 1, 2),
                },
                {
                    "type": "SELL",
                    "ticker": "AAPL",
                    "shares": Decimal("5"),
                    "total_amount": Decimal("900.00"),
                    "date": date(2024, 6, 30),
                },
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 1, 2),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("150.00"),
                    date(2024, 1, 2): Decimal("150.00"),
                    date(2024, 6, 30): Decimal("180.00"),
                    date(2024, 12, 31): Decimal("190.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None

    def test_multiple_tickers(self):
        """Multiple tickers in same portfolio."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 1, 2),
                },
                {
                    "type": "BUY",
                    "ticker": "MSFT",
                    "shares": Decimal("5"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 30),
                },
            ],
            cash_flows=[
                {"amount": Decimal("1500.00"), "created_at": datetime(2024, 1, 2)},
                {"amount": Decimal("1500.00"), "created_at": datetime(2024, 6, 30)},
            ],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("150.00"),
                    date(2024, 1, 2): Decimal("150.00"),
                    date(2024, 12, 31): Decimal("180.00"),
                },
                "MSFT": {
                    date(2024, 6, 29): Decimal("300.00"),
                    date(2024, 6, 30): Decimal("300.00"),
                    date(2024, 12, 31): Decimal("330.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0

    def test_cash_flow_same_day_as_transaction(self):
        """Cash flow and transaction on same date merge into same sub-period."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 15),
                }
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 6, 15),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 1, 1): Decimal("148.00"),
                    date(2024, 6, 15): Decimal("150.00"),
                    date(2024, 12, 31): Decimal("160.00"),
                },
            },
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert twr is not None
        assert twr > 0

    def test_twr_annualisation(self):
        """TWR annualised correctly for < 1 year period."""
        from src.performance.calculations import _compute_twr

        twr, ann = _compute_twr(
            transactions=[
                {
                    "type": "BUY",
                    "ticker": "AAPL",
                    "shares": Decimal("10"),
                    "total_amount": Decimal("1500.00"),
                    "date": date(2024, 6, 15),
                }
            ],
            cash_flows=[
                {
                    "amount": Decimal("1500.00"),
                    "created_at": datetime(2024, 6, 15),
                }
            ],
            price_map={
                "AAPL": {
                    date(2024, 6, 14): Decimal("150.00"),
                    date(2024, 6, 15): Decimal("150.00"),
                    date(2024, 9, 15): Decimal("165.00"),
                },
            },
            start_date=date(2024, 6, 14),
            end_date=date(2024, 9, 15),
        )
        assert twr is not None
        assert ann is not None
        # Annualised should be higher than raw for < 1 year
        assert ann > twr


# ──────────────────────────────────────────────────────────────────────
# _portfolio_value / _get_closest_price — helper tests
# ──────────────────────────────────────────────────────────────────────


class TestPortfolioValue:
    """Tests for portfolio valuation helpers."""

    def test_basic_valuation(self):
        from src.performance.calculations import _portfolio_value

        holdings = {"AAPL": Decimal("10"), "MSFT": Decimal("5")}
        price_map = {
            "AAPL": {date(2024, 12, 31): Decimal("180.00")},
            "MSFT": {date(2024, 12, 31): Decimal("350.00")},
        }
        value = _portfolio_value(holdings, price_map, date(2024, 12, 31))
        assert value == Decimal("10") * Decimal("180") + Decimal("5") * Decimal("350")

    def test_missing_ticker(self):
        from src.performance.calculations import _portfolio_value

        holdings = {"AAPL": Decimal("10"), "MISSING": Decimal("5")}
        price_map = {
            "AAPL": {date(2024, 12, 31): Decimal("180.00")},
        }
        value = _portfolio_value(holdings, price_map, date(2024, 12, 31))
        assert value == Decimal("1800.00")

    def test_empty_holdings(self):
        from src.performance.calculations import _portfolio_value

        assert _portfolio_value({}, {}, date(2024, 12, 31)) == Decimal("0")


class TestGetClosestPrice:
    """Tests for _get_closest_price helper."""

    def test_exact_date_match(self):
        from src.performance.calculations import _get_closest_price

        price_map = {"AAPL": {date(2024, 12, 31): Decimal("180.00")}}
        price = _get_closest_price(price_map, "AAPL", date(2024, 12, 31))
        assert price == Decimal("180.00")

    def test_date_before_target(self):
        from src.performance.calculations import _get_closest_price

        price_map = {"AAPL": {date(2024, 12, 30): Decimal("179.00")}}
        price = _get_closest_price(price_map, "AAPL", date(2024, 12, 31))
        assert price == Decimal("179.00")

    def test_no_price_available(self):
        from src.performance.calculations import _get_closest_price

        price_map = {"AAPL": {date(2025, 1, 2): Decimal("180.00")}}
        price = _get_closest_price(price_map, "AAPL", date(2024, 12, 31))
        assert price is None

    def test_no_data_for_ticker(self):
        from src.performance.calculations import _get_closest_price

        assert _get_closest_price({}, "AAPL", date(2024, 12, 31)) is None


# ──────────────────────────────────────────────────────────────────────
# Benchmark Comparison — pure function tests
# ──────────────────────────────────────────────────────────────────────


class TestBenchmarkComparison:
    """Tests for benchmark comparison."""

    def test_basic_comparison(self):
        """Basic benchmark comparison with portfolio outperformance."""
        from src.performance.calculations import compute_benchmark_comparison

        result = compute_benchmark_comparison(
            portfolio_id="test-id",
            portfolio_twr=Decimal("0.25"),
            benchmark_ticker="SPY",
            benchmark_daily_returns=[Decimal("0.001"), Decimal("0.002")],
            portfolio_daily_returns=[Decimal("0.003"), Decimal("0.004")],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.portfolio_return == Decimal("0.25")
        assert result.benchmark_return is not None
        assert result.benchmark_ticker == "SPY"
        assert result.excess_return_alpha is not None
        assert result.excess_return_alpha > 0

    def test_missing_portfolio_return(self):
        """When portfolio_twr is None, alpha is None."""
        from src.performance.calculations import compute_benchmark_comparison

        result = compute_benchmark_comparison(
            portfolio_id="test-id",
            portfolio_twr=None,
            benchmark_ticker="QQQ",
            benchmark_daily_returns=[Decimal("0.001")],
            portfolio_daily_returns=[Decimal("0.002")],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.excess_return_alpha is None

    def test_empty_daily_returns(self):
        """Empty daily returns → tracking error is None."""
        from src.performance.calculations import compute_benchmark_comparison

        result = compute_benchmark_comparison(
            portfolio_id="test-id",
            portfolio_twr=Decimal("0.10"),
            benchmark_ticker="SPY",
            benchmark_daily_returns=[],
            portfolio_daily_returns=[],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.tracking_error is None
        assert result.information_ratio is None
        assert result.daily_returns_count == 0

    def test_tracking_error_computed(self):
        """Tracking error is computed from excess returns."""
        from src.performance.calculations import compute_benchmark_comparison

        result = compute_benchmark_comparison(
            portfolio_id="test-id",
            portfolio_twr=Decimal("0.10"),
            benchmark_ticker="SPY",
            benchmark_daily_returns=[Decimal("0.01"), Decimal("-0.008"), Decimal("0.003")],
            portfolio_daily_returns=[Decimal("0.015"), Decimal("-0.005"), Decimal("0.01")],
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
        )
        assert result.tracking_error is not None
        assert result.tracking_error > 0
        assert result.daily_returns_count == 3
        # Information ratio should be computed
        assert result.information_ratio is not None


# ──────────────────────────────────────────────────────────────────────
# Router — HTTP integration tests
# ──────────────────────────────────────────────────────────────────────


class TestPerformanceRouter:
    """HTTP-level tests for performance endpoints."""

    async def _create_portfolio_via_api(self, client, auth_headers) -> str:
        resp = await client.post(
            "/portfolios",
            json={"name": "Perf Test Portfolio"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    async def _seed_holding(self, client, auth_headers, portfolio_id: str, ticker: str):
        """Create a holding via API."""
        resp = await client.post(
            f"/portfolios/{portfolio_id}/holdings",
            json={"ticker": ticker, "shares": 10, "average_cost_basis": 150.0},
            headers=auth_headers,
        )
        # May fail if holding already exists — that's OK
        return resp

    async def test_get_performance_empty_portfolio(self, client, auth_headers):
        """GET /portfolio/performance/{id} for empty portfolio returns 200 with zeros."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        resp = await client.get(
            f"/portfolio/performance/{pid}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_holdings"] == 0
        assert data["total_cost_basis"] == 0
        assert data["holdings"] == []

    async def test_get_performance_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = await client.get("/portfolio/performance/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401

    async def test_get_performance_not_found(self, client, auth_headers):
        """Non-existent portfolio returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.get(
            f"/portfolio/performance/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_get_performance_wrong_user(self, client, auth_headers):
        """Portfolio owned by another user returns 404."""
        # Create portfolio as test user
        pid = await self._create_portfolio_via_api(client, auth_headers)
        # Register a second user and try to access it
        resp = await client.post(
            "/auth/register",
            json={
                "email": "other@stocklens.dev",
                "password": "OtherPass123!",
                "full_name": "Other User",
            },
        )
        assert resp.status_code == 201
        other_token = resp.json()["tokens"]["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}

        resp = await client.get(
            f"/portfolio/performance/{pid}",
            headers=other_headers,
        )
        assert resp.status_code == 404

    async def test_get_benchmark_requires_auth(self, client):
        """Unauthenticated benchmark request returns 401."""
        resp = await client.get("/portfolio/benchmark/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 401

    async def test_get_benchmark_not_found(self, client, auth_headers):
        """Non-existent portfolio returns 404 for benchmark."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.get(
            f"/portfolio/benchmark/{fake_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_get_benchmark_invalid_ticker(self, client, auth_headers):
        """Invalid benchmark ticker returns 400."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        resp = await client.get(
            f"/portfolio/benchmark/{pid}?benchmark=INVALID",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "must be SPY or QQQ" in resp.json()["detail"]
