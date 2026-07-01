"""
Pure portfolio computation functions.

No DB access — all data is passed in as arguments for testability.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from src.performance.schemas import (
    BenchmarkComparisonResponse,
    HoldingPerformance,
    PortfolioPerformanceResponse,
)


def compute_holding_performance(
    ticker: str,
    shares: Decimal,
    avg_cost_basis: Decimal,
    current_price: Optional[Decimal],
    previous_close: Optional[Decimal],
    total_portfolio_value: Optional[Decimal],
) -> HoldingPerformance:
    """Compute performance metrics for a single holding.

    Args:
        ticker: Holding ticker.
        shares: Number of shares held.
        avg_cost_basis: Average cost per share.
        current_price: Current market price (None if unavailable).
        previous_close: Previous day's close (None if unavailable).
        total_portfolio_value: Total portfolio value for weight calculation.

    Returns:
        HoldingPerformance with computed metrics.
    """
    cost_basis = shares * avg_cost_basis

    if current_price is not None:
        market_value = shares * current_price
        unrealised_pl = market_value - cost_basis
        if avg_cost_basis > 0:
            unrealised_pl_pct = (current_price - avg_cost_basis) / avg_cost_basis * 100
        else:
            # ponytail: zero-cost-basis holdings (transfers, DRIP) — P&L % is undefined
            unrealised_pl_pct = None
    else:
        market_value = None
        unrealised_pl = None
        unrealised_pl_pct = None

    if current_price is not None and previous_close is not None and previous_close > 0:
        day_change = shares * (current_price - previous_close)
        day_change_pct = (current_price - previous_close) / previous_close * 100
    else:
        day_change = None
        day_change_pct = None

    portfolio_weight_pct = (
        (market_value / total_portfolio_value * 100)
        if market_value is not None and total_portfolio_value and total_portfolio_value > 0
        else None
    )

    return HoldingPerformance(
        ticker=ticker,
        shares=shares,
        average_cost_basis=avg_cost_basis,
        current_price=current_price,
        market_value=market_value,
        cost_basis=cost_basis,
        unrealised_pl=unrealised_pl,
        unrealised_pl_pct=unrealised_pl_pct,
        day_change=day_change,
        day_change_pct=day_change_pct,
        portfolio_weight_pct=portfolio_weight_pct,
    )


def compute_portfolio_performance(
    portfolio_id: str,
    portfolio_name: str,
    holdings_data: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    cash_flows: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    enable_twr: bool = True,
) -> PortfolioPerformanceResponse:
    """Compute aggregate portfolio performance including TWR.

    Args:
        portfolio_id: UUID of the portfolio.
        portfolio_name: Display name.
        holdings_data: List of holding rows from DB (with ticker, shares, avg_cost_basis).
        transactions: List of transaction rows from DB (with type, ticker, shares,
                      total_amount, date). Must be sorted by date ascending.
        cash_flows: List of cash flow rows from DB (with amount, created_at).
        price_map: Nested dict: {ticker: {date: adjusted_close}}.
        start_date: Start of analysis period (defaults to 1 year ago).
        end_date: End of analysis period (defaults to today).
        enable_twr: If False, skip TWR computation (returns None for TWR fields).

    Returns:
        PortfolioPerformanceResponse with computed metrics.
    """
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    # ── 1. Get current prices ──
    latest_prices: dict[str, Decimal] = {}
    previous_closes: dict[str, Decimal] = {}
    for h in holdings_data:
        ticker = h["ticker"]
        ticker_prices = price_map.get(ticker, {})
        if ticker_prices:
            sorted_dates = sorted(ticker_prices.keys())
            latest_prices[ticker] = ticker_prices[sorted_dates[-1]]
            if len(sorted_dates) >= 2:
                previous_closes[ticker] = ticker_prices[sorted_dates[-2]]

    # ── 2. Per-holding metrics ──
    holdings_with_prices = 0
    holdings_total = len(holdings_data)

    holdings_perf = []
    total_market_value = Decimal(0)
    total_cost_basis = Decimal(0)

    for h in holdings_data:
        ticker = h["ticker"]
        shares = h["shares"]
        avg_cost = h["average_cost_basis"]

        hp = compute_holding_performance(
            ticker=ticker,
            shares=shares,
            avg_cost_basis=avg_cost,
            current_price=latest_prices.get(ticker),
            previous_close=previous_closes.get(ticker),
            total_portfolio_value=None,  # Will recalc after we know the total
        )
        if hp.market_value is not None:
            total_market_value += hp.market_value
            holdings_with_prices += 1
        total_cost_basis += hp.cost_basis
        holdings_perf.append(hp)

    # Recalculate weights now that we have total_market_value
    for hp in holdings_perf:
        if hp.market_value is not None and total_market_value > 0:
            hp.portfolio_weight_pct = hp.market_value / total_market_value * 100

    # ── 3. Portfolio-level P&L ──
    if total_market_value > 0 and total_cost_basis > 0:
        total_unrealised_pl = total_market_value - total_cost_basis
        total_unrealised_pl_pct = (total_unrealised_pl / total_cost_basis) * 100
    else:
        total_unrealised_pl = total_market_value - total_cost_basis if total_market_value else None
        total_unrealised_pl_pct = None

    # ── 4. Day Change ──
    # ponytail: day-change weights use previous_close × shares (start-of-day value).
    # Using current_price × shares would slightly bias toward holdings with larger
    # intraday gains. The difference is negligible for daily moves <2%.
    total_day_change = Decimal(0)
    total_day_change_pct = None
    day_change_computed = 0
    for hp in holdings_perf:
        if hp.day_change is not None:
            total_day_change += hp.day_change
            day_change_computed += 1
    if day_change_computed > 0:
        # Weighted by start-of-day value
        weights = {
            hp.ticker: (
                hp.market_value / (Decimal(1) + hp.day_change_pct / Decimal(100))
                if hp.market_value and hp.day_change_pct
                else Decimal(0)
            )
            for hp in holdings_perf
            if hp.day_change is not None
        }
        total_weight = sum(weights.values())
        if total_weight > 0:
            weighted_sum = sum(
                (hp.day_change_pct or Decimal(0))
                * weights.get(hp.ticker, Decimal(0))
                / total_weight
                for hp in holdings_perf
            )
            total_day_change_pct = weighted_sum

    # ── 5. Free cash balance ──
    total_deposits = sum(cf["amount"] for cf in cash_flows)
    net_invested = sum(t["total_amount"] for t in transactions if t["type"] == "BUY") - sum(
        t["total_amount"] for t in transactions if t["type"] == "SELL"
    )
    free_cash_balance = total_deposits - net_invested

    # ── 6. TWR ──
    twr: Optional[Decimal] = None
    twr_annualised: Optional[Decimal] = None
    if enable_twr:
        twr, twr_annualised = _compute_twr(
            transactions=transactions,
            cash_flows=cash_flows,
            price_map=price_map,
            start_date=start_date,
            end_date=end_date,
        )

    # ── 7. Data quality ──
    data_quality = "complete" if holdings_with_prices == holdings_total else "partial"

    return PortfolioPerformanceResponse(
        portfolio_id=portfolio_id,
        portfolio_name=portfolio_name,
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_unrealised_pl=total_unrealised_pl,
        total_unrealised_pl_pct=total_unrealised_pl_pct,
        day_change=total_day_change if day_change_computed > 0 else None,
        day_change_pct=total_day_change_pct,
        free_cash_balance=free_cash_balance,
        twr=twr,
        twr_annualised=twr_annualised,
        twr_start_date=start_date,
        twr_end_date=end_date,
        holdings=holdings_perf,
        total_holdings=holdings_total,
        data_quality=data_quality,
        calculated_at=datetime.now(timezone.utc),
    )


def _compute_twr(
    transactions: list[dict[str, Any]],
    cash_flows: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Compute Time-Weighted Return using daily linking methodology.

    Cash flows (explicit deposits) and transactions (BUY/SELL for holdings)
    are separate signals. Cash flow amounts are the external CF for TWR;
    transactions determine holdings state only.
    """
    relevant_txns = [t for t in transactions if t["date"] <= end_date]

    if not relevant_txns and not cash_flows:
        return None, None

    # Merge transaction dates and cash flow dates
    txn_dates = sorted({t["date"] for t in relevant_txns if start_date <= t["date"] <= end_date})
    cf_dates = sorted(
        {
            cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"]
            for cf in cash_flows
            if start_date
            <= (cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"])
            <= end_date
        }
    )
    all_dates = sorted(set([start_date] + txn_dates + cf_dates + [end_date]))

    # Build lookup maps
    txns_by_date: dict[date, list[dict]] = defaultdict(list)
    for t in relevant_txns:
        txns_by_date[t["date"]].append(t)

    cfs_by_date: dict[date, Decimal] = defaultdict(Decimal)
    for cf in cash_flows:
        cf_date = cf["created_at"].date() if hasattr(cf["created_at"], "date") else cf["created_at"]
        if start_date <= cf_date <= end_date:
            cfs_by_date[cf_date] += cf["amount"]

    # Seed initial holdings from transactions before start_date
    current_holdings: dict[str, Decimal] = {}
    for txn in relevant_txns:
        if txn["date"] >= start_date:
            continue
        if txn["type"] == "BUY":
            current_holdings[txn["ticker"]] = (
                current_holdings.get(txn["ticker"], Decimal(0)) + txn["shares"]
            )
        else:
            current_holdings[txn["ticker"]] = (
                current_holdings.get(txn["ticker"], Decimal(0)) - txn["shares"]
            )
            if current_holdings[txn["ticker"]] <= 0:
                del current_holdings[txn["ticker"]]

    cumulative_return = Decimal(1)
    sub_period_count = 0

    for i in range(len(all_dates) - 1):
        sub_start = all_dates[i]
        sub_end = all_dates[i + 1]

        # 1. BMV before sub_end transactions
        bmv = _portfolio_value(current_holdings, price_map, sub_start)

        # 2. Apply sub_end transactions (update holdings)
        for txn in txns_by_date.get(sub_end, []):
            ticker = txn["ticker"]
            if txn["type"] == "BUY":
                current_holdings[ticker] = current_holdings.get(ticker, Decimal(0)) + txn["shares"]
            else:
                current_holdings[ticker] = current_holdings.get(ticker, Decimal(0)) - txn["shares"]
                if current_holdings[ticker] <= 0:
                    del current_holdings[ticker]

        # 3. EMV after sub_end
        emv = _portfolio_value(current_holdings, price_map, sub_end)

        # 4. Cash flow for this sub-period = deposits on sub_end
        cf_total = cfs_by_date.get(sub_end, Decimal(0))

        if bmv == 0 and cf_total > 0:
            sub_return = Decimal(0)
        elif bmv == 0:
            continue
        else:
            sub_return = (emv - bmv - cf_total) / bmv

        cumulative_return *= Decimal(1) + sub_return
        sub_period_count += 1

    if sub_period_count == 0:
        return None, None

    twr = cumulative_return - Decimal(1)
    days = (end_date - start_date).days
    if days > 0:
        twr_annualised = (Decimal(1) + twr) ** (Decimal(365) / Decimal(days)) - Decimal(1)
    else:
        twr_annualised = None

    return twr, twr_annualised


def _portfolio_value(
    holdings: dict[str, Decimal],
    price_map: dict[str, dict[date, Decimal]],
    valuation_date: date,
) -> Decimal:
    """Compute total market value of holdings at a given date.

    Uses the closest available price (last available before the valuation date).
    """
    total = Decimal(0)
    for ticker, shares in holdings.items():
        price = _get_closest_price(price_map, ticker, valuation_date)
        if price is not None:
            total += shares * price
    return total


def _get_closest_price(
    price_map: dict[str, dict[date, Decimal]],
    ticker: str,
    target_date: date,
) -> Optional[Decimal]:
    """Get the closest available adjusted_close for a ticker at/before *target_date*."""
    ticker_prices = price_map.get(ticker)
    if not ticker_prices:
        return None

    available_dates = [d for d in ticker_prices if d <= target_date]
    if not available_dates:
        return None

    closest = max(available_dates)
    return ticker_prices[closest]


def compute_benchmark_comparison(
    portfolio_id: str,
    portfolio_twr: Optional[Decimal],
    benchmark_ticker: str,
    benchmark_daily_returns: list[Decimal],
    portfolio_daily_returns: list[Decimal],
    period_start: date,
    period_end: date,
) -> BenchmarkComparisonResponse:
    """Compute portfolio vs benchmark comparison metrics.

    Args:
        portfolio_id: UUID of the portfolio.
        portfolio_twr: Portfolio TWR over the period.
        benchmark_ticker: Ticker of the benchmark (SPY/QQQ).
        benchmark_daily_returns: Daily benchmark returns for tracking error.
        portfolio_daily_returns: Daily portfolio returns for tracking error.
        period_start: Start of comparison period.
        period_end: End of comparison period.

    Returns:
        BenchmarkComparisonResponse.
    """
    # Benchmark return from adjusted_close prices: simple geometric linking
    benchmark_return = Decimal(1)
    for r in benchmark_daily_returns:
        benchmark_return *= Decimal(1) + r
    benchmark_return -= Decimal(1)

    # Excess return (alpha)
    if portfolio_twr is not None and benchmark_return is not None:
        excess_return = portfolio_twr - benchmark_return
    else:
        excess_return = None

    # Tracking error: standard deviation of daily excess returns
    tracking_error = None
    information_ratio = None
    daily_returns_count = 0

    if portfolio_daily_returns and benchmark_daily_returns:
        min_len = min(len(portfolio_daily_returns), len(benchmark_daily_returns))
        daily_returns_count = min_len
        excess_returns = [
            portfolio_daily_returns[i] - benchmark_daily_returns[i] for i in range(min_len)
        ]
        if excess_returns:
            n = len(excess_returns)
            mean_excess = sum(excess_returns) / Decimal(n)
            variance = sum((r - mean_excess) ** 2 for r in excess_returns) / Decimal(n)
            tracking_error = variance.sqrt()

            if tracking_error > 0:
                annualised_excess = mean_excess * Decimal(252)
                annualised_te = tracking_error * Decimal(252).sqrt()
                information_ratio = annualised_excess / annualised_te

    return BenchmarkComparisonResponse(
        portfolio_id=portfolio_id,
        benchmark_ticker=benchmark_ticker,
        portfolio_return=portfolio_twr,
        benchmark_return=benchmark_return,
        excess_return_alpha=excess_return,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        period_start=period_start,
        period_end=period_end,
        daily_returns_count=daily_returns_count,
        calculated_at=datetime.now(timezone.utc),
    )
