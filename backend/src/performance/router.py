"""
FastAPI router for portfolio performance and benchmark comparison.

Endpoints:
    - ``GET /portfolio/performance/{portfolio_id}`` — portfolio P&L, TWR, holdings breakdown
    - ``GET /portfolio/benchmark/{portfolio_id}`` — portfolio vs benchmark comparison
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
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
from src.market.repository import get_ohlcv
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
) -> dict[str, dict[date, Decimal]]:
    """Build a nested price map {ticker: {date: adjusted_close}} for the given range.

    Uses ``asyncio.gather`` to fetch all tickers in parallel.
    """
    import asyncio

    # ponytail: gather with return_exceptions=True means results are list[Any | BaseException]
    ohlcv_tasks = [
        get_ohlcv(ticker, start_date=start_date, end_date=end_date, limit=2000)
        for ticker in tickers
    ]
    results = await asyncio.gather(  # type: ignore[assignment]
        *ohlcv_tasks,
        return_exceptions=True,
    )

    price_map: dict[str, dict[date, Decimal]] = {}
    for ticker, rows in zip(tickers, results):
        if isinstance(rows, Exception):
            logger.warning("price_map_fetch_failed", ticker=ticker, error=str(rows))
            price_map[ticker] = {}
        else:
            price_map[ticker] = {
                r["date"]: r["adjusted_close"] for r in rows if r["adjusted_close"] is not None
            }
    return price_map


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
        start_date = end_date.replace(year=end_date.year - 1)

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
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date.replace(year=end_date.year - 1)

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
    price_map = await _build_price_map(all_tickers, start_date, end_date)

    if not price_map.get(benchmark):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for benchmark {benchmark}",
        )

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
    portfolio_daily_returns = _compute_portfolio_daily_returns(
        holdings=holdings,
        transactions=transactions,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
    )

    return compute_benchmark_comparison(
        portfolio_id=str(portfolio_id),
        portfolio_twr=perf_response.twr,
        benchmark_ticker=benchmark,
        benchmark_daily_returns=benchmark_daily_returns,
        portfolio_daily_returns=portfolio_daily_returns,
        period_start=start_date,
        period_end=end_date,
    )


def _compute_portfolio_daily_returns(
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
) -> list[Decimal]:
    """Compute daily portfolio returns for tracking error calculation.

    Reconstructs holdings at each trading day and computes day-over-day
    percentage return. Returns empty list if insufficient price data.
    """
    all_dates: set[date] = set()
    for ticker_prices in price_map.values():
        all_dates.update(ticker_prices.keys())
    if not all_dates:
        return []
    trading_days = sorted(d for d in all_dates if start_date <= d <= end_date)
    if len(trading_days) < 2:
        return []

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

    return daily_returns
