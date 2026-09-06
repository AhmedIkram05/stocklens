"""
FastAPI router for market data endpoints.

Endpoints:
    - ``GET /market/ohlcv/{ticker}`` — historical OHLCV (DB cache → yfinance)
    - ``GET /market/quote/{ticker}`` — current quote (Redis cache → yfinance)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.limiter import limiter
from src.market.provider import fetch_ohlcv
from src.market.quotes import get_quote
from src.market.repository import (
    get_latest_ohlcv_date,
    get_ohlcv,
    upsert_ohlcv,
)
from src.market.schemas import (
    OHLCVData,
    OHLCVResponse,
    QuoteResponse,
)

logger = structlog.get_logger()

router = APIRouter()


async def refresh_ohlcv_if_stale(ticker: str) -> bool:
    """Check cache freshness and fetch from yfinance if stale.

    Returns True if data was refreshed (or fetched for the first time).
    """
    latest_db_date = await get_latest_ohlcv_date(ticker)

    # Cache HIT: newest data is yesterday or newer
    # Weekend tolerance: on Monday, accept Friday's data (3-day gap)
    staleness_days = 3 if date.today().weekday() == 0 else 1
    cutoff = date.today() - timedelta(days=staleness_days)
    if latest_db_date is not None and latest_db_date >= cutoff:
        return False

    # Cache MISS or stale: fetch from yfinance
    logger.info("fetching_ohlcv_from_yfinance", ticker=ticker)

    try:
        rows = await fetch_ohlcv(ticker, start_date=None, end_date=None)
    except Exception as exc:
        logger.error("yfinance_ohlcv_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Market data temporarily unavailable for {ticker}",
        )

    if not rows:
        logger.warning("yfinance_returned_empty", ticker=ticker)
        return False

    inserted = await upsert_ohlcv(ticker, rows)
    logger.info(
        "ohlcv_cached",
        ticker=ticker,
        rows_fetched=len(rows),
        rows_inserted=inserted,
    )
    return True


def _row_to_ohlcv_data(row: dict[str, Any]) -> OHLCVData:
    return OHLCVData(
        date=row["date"],
        open=row.get("open"),
        high=row.get("high"),
        low=row.get("low"),
        close=row.get("close"),
        adjusted_close=row.get("adjusted_close"),
        volume=row.get("volume"),
    )


@router.get("/ohlcv/{ticker}", response_model=OHLCVResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_ohlcv_endpoint(
    request: Request,
    ticker: str,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: UserInDB = Depends(get_current_user),
) -> OHLCVResponse:
    """Return historical OHLCV data for a ticker.

    Data is served from the PostgreSQL cache when available and fresh.
    Stale or missing data triggers a refresh from yfinance.
    Requires authentication (any authenticated user can fetch market data).
    """
    ticker = ticker.upper()

    # Attempt to refresh cache if data is stale
    await refresh_ohlcv_if_stale(ticker)

    # Set date defaults after (potential) refresh
    if start_date is None:
        start_date = date.today() - timedelta(days=365)
    if end_date is None:
        end_date = date.today()

    rows = await get_ohlcv(ticker, start_date=start_date, end_date=end_date)

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for {ticker}",
        )

    data = [_row_to_ohlcv_data(r) for r in rows]
    return OHLCVResponse(ticker=ticker, data=data, total=len(data))


@router.get("/quote/{ticker}", response_model=QuoteResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_quote_endpoint(
    request: Request,
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
) -> QuoteResponse:
    """Return current quote for a ticker.

    Uses a 60-second Redis cache to avoid hammering yfinance.
    Cache is per-ticker (key: ``quote:{ticker}``).
    """
    ticker = ticker.upper()

    # Cached fetch (provider failures propagate → 503 below)
    try:
        quote_data = await get_quote(ticker)
    except Exception as exc:
        logger.error("yfinance_quote_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Quote temporarily unavailable for {ticker}",
        )

    return QuoteResponse(
        ticker=quote_data["ticker"],
        price=quote_data["price"],
        change=quote_data["change"],
        change_pct=quote_data["change_pct"],
        previous_close=quote_data["previous_close"],
        volume=quote_data["volume"],
        timestamp=quote_data["timestamp"],
        currency=quote_data.get("currency", "GBP"),
        exchange=quote_data.get("exchange"),
    )
