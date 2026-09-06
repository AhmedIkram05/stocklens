"""
FastAPI router for portfolio performance and benchmark comparison.

Endpoints:
    - ``GET /portfolio/performance/{portfolio_id}`` — portfolio P&L, TWR, holdings breakdown
    - ``GET /portfolio/benchmark/{portfolio_id}`` — portfolio vs benchmark comparison
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.limiter import limiter
from src.performance import queries
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

    return await queries.get_bulk_portfolio_performance(ids, current_user.id)


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
