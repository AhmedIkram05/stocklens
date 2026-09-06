"""
FastAPI router for portfolio performance and benchmark comparison.

Endpoints:
    - ``GET /portfolio/performance/{portfolio_id}`` — portfolio P&L, TWR, holdings breakdown
    - ``GET /portfolio/benchmark/{portfolio_id}`` — portfolio vs benchmark comparison
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.limiter import limiter
from src.performance import queries
from src.performance.calculations import compute_portfolio_performance
from src.performance.schemas import (
    BenchmarkComparisonResponse,
    BulkPerformanceResponse,
    PortfolioPerformanceResponse,
)

router = APIRouter()


# ── Bulk endpoint (must be registered before the parameterised route) ────────


@router.get(
    "/portfolio/performance/bulk",
    response_model=BulkPerformanceResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def bulk_portfolio_performance(
    request: Request,
    portfolio_ids: str = Query(..., description="Comma-separated portfolio UUIDs"),
    current_user: UserInDB = Depends(get_current_user),
) -> BulkPerformanceResponse:
    """Return performance metrics for multiple portfolios in one call.

    Avoids the N+1 problem from calling the single-portfolio endpoint N times
    by batching all database reads into a handful of bulk queries.
    """
    ids = [p.strip() for p in portfolio_ids.split(",") if p.strip()]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one portfolio_id is required",
        )

    # 1. Verify ownership + get portfolio names (1 query)
    portfolio_names = await queries.batch_verify_ownership(ids, current_user.id)
    if not portfolio_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolios found for this user",
        )

    # 2. Batch all domain data (3 queries total)
    holdings_by_pid = await queries.batch_get_holdings(ids)
    txns_by_pid = await queries.batch_get_transactions(ids)
    cfs_by_pid = await queries.batch_get_cash_flows(ids)

    # 3. Collect all unique tickers across all portfolios
    all_tickers: set[str] = set()
    for holdings in holdings_by_pid.values():
        all_tickers.update(h["ticker"] for h in holdings)

    # Price data (batched across all tickers)
    end_date = date.today()
    start_date = end_date - timedelta(days=365)

    if all_tickers:
        tickers = list(all_tickers)
        price_map = await queries.build_price_map(tickers, start_date, end_date)
        live_quotes = await queries.fetch_live_quotes(tickers)

        # FX rates per ticker
        fx_rates: dict[str, Decimal] = {}
        for holdings in holdings_by_pid.values():
            for h in holdings:
                t = h["ticker"]
                if t not in fx_rates and h.get("fx_rate_to_gbp") is not None:
                    fx_rates[t] = h["fx_rate_to_gbp"]
    else:
        price_map = {}
        live_quotes = {}
        fx_rates = {}

    # 4. Compute per-portfolio performance
    results: dict[str, PortfolioPerformanceResponse] = {}
    for pid in ids:
        name = portfolio_names.get(pid)
        if name is None:
            continue

        holdings = holdings_by_pid.get(pid, [])
        transactions = txns_by_pid.get(pid, [])
        cash_flows = cfs_by_pid.get(pid, [])

        if not holdings:
            # Empty portfolio — just compute free cash
            total_deposits = sum(
                (Decimal(str(cf["amount"])) for cf in cash_flows),
                Decimal(0),
            )
            net_invested = sum(
                (
                    Decimal(str(t.get("total_amount_gbp", t["total_amount"])))
                    for t in transactions
                    if t["type"] == "BUY"
                ),
                Decimal(0),
            ) - sum(
                (
                    Decimal(str(t.get("total_amount_gbp", t["total_amount"])))
                    for t in transactions
                    if t["type"] == "SELL"
                ),
                Decimal(0),
            )
            results[pid] = PortfolioPerformanceResponse(
                portfolio_id=pid,
                portfolio_name=name,
                total_cost_basis=Decimal(0),
                twr=None,
                twr_methodology="cash-flow-based",
                total_holdings=0,
                free_cash_balance=total_deposits - net_invested,
                holdings=[],
                data_quality="complete",
                calculated_at=datetime.now(timezone.utc),
            )
        else:
            results[pid] = compute_portfolio_performance(
                portfolio_id=pid,
                portfolio_name=name,
                holdings_data=holdings,
                transactions=transactions,
                cash_flows=cash_flows,
                price_map=price_map,
                start_date=start_date,
                end_date=end_date,
                enable_twr=settings.ENABLE_TWR,
                live_quotes=live_quotes,
                fx_rates=fx_rates,
            )

    return BulkPerformanceResponse(portfolios=results)


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
    return await queries.get_portfolio_performance(
        portfolio_id=portfolio_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
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
        return await queries.get_benchmark_comparison(
            portfolio_id, benchmark, start_date, end_date, current_user.id
        )
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("Benchmark comparison failed: %s", exc)
        raise
