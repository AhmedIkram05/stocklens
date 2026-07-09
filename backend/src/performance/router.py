"""
FastAPI router for portfolio performance and benchmark comparison.

Endpoints:
    - ``GET /portfolio/performance/{portfolio_id}`` — portfolio P&L, TWR, holdings breakdown
    - ``GET /portfolio/benchmark/{portfolio_id}`` — portfolio vs benchmark comparison
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from src.market.provider import fetch_ohlcv, fetch_quote
from src.market.repository import get_earliest_ohlcv_date, get_ohlcv_batch, upsert_ohlcv
from src.market.router import _refresh_ohlcv_if_stale
from src.performance.calculations import (
    compute_benchmark_comparison,
    compute_portfolio_performance,
)
from src.performance.schemas import (
    BenchmarkComparisonResponse,
    PortfolioPerformanceResponse,
)

logger = structlog.get_logger()

router = APIRouter()


async def _verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, user_id, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


async def _get_holdings(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch holdings for a portfolio."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, ticker, shares, average_cost_basis "
            "FROM holdings WHERE portfolio_id = $1::uuid "
            "ORDER BY ticker",
            portfolio_id,
        )
    return [dict(r) for r in rows]


async def _get_transactions_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all transactions for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, ticker, type, shares, price_per_share, total_amount, transaction_date "
            "FROM transactions WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date ASC, created_at ASC, id ASC",
            portfolio_id,
        )
    result = []
    for r in rows:
        d = dict(r)
        d["date"] = d.pop("transaction_date")
        result.append(d)
    return result


async def _get_cash_flows_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all cash flows for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at ASC, id ASC",
            portfolio_id,
        )
    return [dict(r) for r in rows]


async def _get_free_cash_balance(portfolio_id: str) -> Decimal:
    """Compute free cash = total deposits - net invested (BUYs - SELLs)."""
    async with connection_ctx() as conn:
        total_deposits = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
        net_invested = await conn.fetchval(
            "SELECT COALESCE(SUM(CASE WHEN type = 'BUY' THEN total_amount "
            "WHEN type = 'SELL' THEN -total_amount ELSE 0 END), 0) "
            "FROM transactions WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    return Decimal(str(total_deposits)) - Decimal(str(net_invested))


async def _build_price_map(
    tickers: list[str],
    start_date: date,
    end_date: date,
    *,
    limit: int = 50000,
) -> dict[str, dict[date, Decimal]]:
    """Build a nested price map {ticker: {date: adjusted_close}} for the given range.

    Uses a single batched query to fetch all tickers in parallel.
    """
    # Fetch all tickers in one batched query
    batch_results = await get_ohlcv_batch(
        tickers, start_date=start_date, end_date=end_date, limit=limit
    )

    price_map: dict[str, dict[date, Decimal]] = {}
    for ticker in tickers:
        rows = batch_results.get(ticker, [])
        price_map[ticker] = {
            r["date"]: r["adjusted_close"] for r in rows if r["adjusted_close"] is not None
        }
    return price_map


async def _fetch_live_quotes(
    tickers: list[str],
) -> dict[str, tuple[Decimal, Decimal]]:
    """Fetch live quotes in parallel, returning {ticker: (price, previous_close)}.

    Failures are logged and silently skipped — the caller falls back to OHLCV data.
    """
    import asyncio

    tasks = [fetch_quote(t) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    quotes: dict[str, tuple[Decimal, Decimal]] = {}
    for ticker, result in zip(tickers, results):
        if isinstance(result, Exception):
            logger.warning("live_quote_fetch_failed", ticker=ticker, error=str(result))
            continue
        quotes[ticker] = (result["price"], result["previous_close"])
    return quotes


@router.get(
    "/portfolio/performance/{portfolio_id}",
    response_model=PortfolioPerformanceResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_portfolio_performance(
    request: Request,
    portfolio_id: UUID,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioPerformanceResponse:
    """Return portfolio performance metrics including TWR and per-holding P&L.

    Requires the portfolio to belong to the current user.
    Data freshness depends on market data cache (see /market/ohlcv/{ticker}).
    """
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    holdings = await _get_holdings(str(portfolio_id))
    if not holdings:
        free_cash = await _get_free_cash_balance(str(portfolio_id))
        return PortfolioPerformanceResponse(
            portfolio_id=str(portfolio_id),
            portfolio_name=portfolio["name"],
            total_cost_basis=Decimal(0),
            twr=None,
            twr_methodology="cash-flow-based",
            total_holdings=0,
            free_cash_balance=free_cash,
            holdings=[],
            data_quality="complete",
            calculated_at=datetime.now(timezone.utc),
        )

    transactions = await _get_transactions_sorted(str(portfolio_id))
    cash_flows = await _get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    price_map = await _build_price_map(tickers, start_date, end_date)

    # Fetch live intraday quotes to override OHLCV closing prices
    live_quotes = await _fetch_live_quotes(tickers)

    return compute_portfolio_performance(
        portfolio_id=str(portfolio_id),
        portfolio_name=portfolio["name"],
        holdings_data=holdings,
        transactions=transactions,
        cash_flows=cash_flows,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
        enable_twr=settings.ENABLE_TWR,
        live_quotes=live_quotes,
    )


@router.get(
    "/portfolio/benchmark/{portfolio_id}",
    response_model=BenchmarkComparisonResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_benchmark_comparison(
    request: Request,
    portfolio_id: UUID,
    benchmark: str = Query("SPY", description="Benchmark ticker (SPY or QQQ)"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> BenchmarkComparisonResponse:
    """Compare portfolio performance to a benchmark index.

    Returns alpha (excess return), tracking error, and information ratio.
    """
    import logging

    _logger = logging.getLogger("performance.benchmark")
    try:
        return await _get_benchmark_comparison_inner(
            portfolio_id, benchmark, start_date, end_date, current_user
        )
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("Benchmark comparison failed: %s", exc)
        raise


async def _get_benchmark_comparison_inner(
    portfolio_id: UUID,
    benchmark: str,
    start_date: Optional[date],
    end_date: Optional[date],
    current_user,
) -> BenchmarkComparisonResponse:
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    benchmark = benchmark.upper()
    if benchmark not in ("SPY", "QQQ"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Benchmark must be SPY or QQQ",
        )

    holdings = await _get_holdings(str(portfolio_id))
    transactions = await _get_transactions_sorted(str(portfolio_id))
    cash_flows = await _get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    all_tickers = list(set(tickers + [benchmark]))

    # Ensure benchmark OHLCV data covers the requested start_date.
    # _refresh_ohlcv_if_stale only checks recency (1-3 days), not depth.
    # yfinance defaults to 1 year when start_date=None, so longer periods
    # may need a wider fetch.
    await _refresh_ohlcv_if_stale(benchmark)
    earliest = await get_earliest_ohlcv_date(benchmark)
    logger.info(
        "coverage_check", benchmark=benchmark, earliest=str(earliest), start_date=str(start_date)
    )
    if earliest is None or earliest > start_date:
        rows = await fetch_ohlcv(benchmark, start_date=start_date, end_date=end_date)
        logger.info("coverage_fetch", benchmark=benchmark, rows_fetched=len(rows))
        if rows:
            inserted = await upsert_ohlcv(benchmark, rows)
            logger.info("coverage_upsert", benchmark=benchmark, rows_inserted=inserted)

    price_map = await _build_price_map(all_tickers, start_date, end_date, limit=50000)

    if not price_map.get(benchmark):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for benchmark {benchmark}",
        )

    # Fetch live quote for benchmark intraday price
    live_quotes = await _fetch_live_quotes(tickers)

    perf_response = compute_portfolio_performance(
        portfolio_id=str(portfolio_id),
        portfolio_name=portfolio["name"],
        holdings_data=holdings,
        transactions=transactions,
        cash_flows=cash_flows,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
        enable_twr=settings.ENABLE_TWR,
        live_quotes=live_quotes,
    )

    # Compute benchmark daily returns from price data
    benchmark_prices = price_map.get(benchmark, {})
    benchmark_dates = sorted(benchmark_prices.keys())
    benchmark_daily_returns = []
    for i in range(1, len(benchmark_dates)):
        prev_price = benchmark_prices[benchmark_dates[i - 1]]
        curr_price = benchmark_prices[benchmark_dates[i]]
        if prev_price > 0:
            benchmark_daily_returns.append((curr_price - prev_price) / prev_price)

    # Compute portfolio daily returns
    portfolio_dates, portfolio_daily_returns = _compute_portfolio_daily_returns(
        holdings=holdings,
        transactions=transactions,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
    )

    # Build cumulative return series for charting
    def _cumulative_series(dates: list[date], returns: list[Decimal]) -> list[dict[str, Any]]:
        cum = Decimal(1)
        series: list[dict[str, Any]] = []
        for i, r in enumerate(returns):
            cum *= Decimal(1) + r
            series.append({"date": str(dates[i + 1]), "value": float(cum - 1)})
        return series

    portfolio_cum = _cumulative_series(portfolio_dates, portfolio_daily_returns)
    benchmark_cum = _cumulative_series(benchmark_dates, benchmark_daily_returns)

    comparison = compute_benchmark_comparison(
        portfolio_id=str(portfolio_id),
        portfolio_twr=perf_response.twr,
        benchmark_ticker=benchmark,
        benchmark_daily_returns=benchmark_daily_returns,
        portfolio_daily_returns=portfolio_daily_returns,
        period_start=start_date,
        period_end=end_date,
    )
    comparison.portfolio_cumulative_returns = portfolio_cum
    comparison.benchmark_cumulative_returns = benchmark_cum
    return comparison


def _compute_portfolio_daily_returns(
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
) -> tuple[list[date], list[Decimal]]:
    """Compute daily portfolio returns for tracking error calculation.

    Reconstructs holdings at each trading day and computes day-over-day
    percentage return. Returns (trading_days, daily_returns).
    """
    all_dates: set[date] = set()
    for ticker_prices in price_map.values():
        all_dates.update(ticker_prices.keys())
    if not all_dates:
        return [], []
    trading_days = sorted(d for d in all_dates if start_date <= d <= end_date)
    if len(trading_days) < 2:
        return [], []

    txns_by_date: dict[date, list[dict]] = defaultdict(list)
    for t in transactions:
        txns_by_date[t["date"]].append(t)

    daily_returns: list[Decimal] = []
    current: dict[str, Decimal] = {}
    previous_value = Decimal(0)

    for i, day in enumerate(trading_days):
        for txn in txns_by_date.get(day, []):
            ticker = txn["ticker"]
            if txn["type"] == "BUY":
                current[ticker] = current.get(ticker, Decimal(0)) + txn["shares"]
            else:
                current[ticker] = current.get(ticker, Decimal(0)) - txn["shares"]
                if current[ticker] <= 0:
                    del current[ticker]

        value = Decimal(0)
        for ticker, shares in current.items():
            ticker_prices = price_map.get(ticker, {})
            if day in ticker_prices and ticker_prices[day] is not None:
                value += shares * ticker_prices[day]

        if i > 0:
            prev = previous_value
            if prev > 0:
                daily_return = (value - prev) / prev
                daily_returns.append(daily_return)
            else:
                daily_returns.append(Decimal(0))

        previous_value = value

    return trading_days, daily_returns
