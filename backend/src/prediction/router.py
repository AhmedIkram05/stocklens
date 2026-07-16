"""
FastAPI router for LSTM prediction endpoint.

Endpoints:
    - GET /predict/{ticker} — Directional forecast with Redis 6h cache

Registered in main.py under prefix /predict.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.cache.redis import get_redis
from src.config import settings
from src.limiter import limiter
from src.market.repository import get_ohlcv as fetch_ohlcv
from src.prediction.schemas import PredictionResponse
from src.prediction.service import prediction_service

logger = structlog.get_logger()

router = APIRouter()

PREDICTION_CACHE_TTL = 21600  # 6 hours


@router.get("/{ticker}", response_model=PredictionResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def predict(
    request: Request,
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
) -> PredictionResponse:
    """Return directional forecast for a ticker.

    Uses the champion GlobalLSTM model loaded at startup.
    Results are cached in Redis for 6 hours (per ticker).

    Requires authentication (any authenticated user can fetch predictions).
    """
    ticker = ticker.upper()
    cache_key = f"predict:{ticker}"

    # Check Redis cache first
    r = None
    try:
        r = await get_redis()
        if r is not None:
            cached = await r.get(cache_key)
            if cached is not None:
                try:
                    data = json.loads(cached)
                    return PredictionResponse(**data, cached=True)
                except (json.JSONDecodeError, TypeError):
                    pass  # Corrupted cache — recompute
    except Exception:
        logger.warning("redis_cache_read_failed", ticker=ticker)

    # Check model loaded
    if not prediction_service.is_loaded():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prediction model not yet loaded. Train and deploy a champion model first.",
        )

    # Fetch OHLCV data (90+ days for feature computation)
    rows = await fetch_ohlcv(ticker, limit=500)
    if not rows or len(rows) < 60:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Insufficient price data for {ticker}. Need at least 60 trading days.",
        )

    # Fetch SPY benchmark data for cross-sectional features
    spy_rows = None
    try:
        spy_rows = await fetch_ohlcv("SPY", limit=500)
    except Exception:
        logger.warning("spy_data_fetch_failed", ticker=ticker)

    # Run prediction (with SPY data for cross-sectional features)
    try:
        result = prediction_service.predict(ticker, rows, spy_ohlcv_rows=spy_rows)
    except Exception as exc:
        logger.exception("prediction_failed", ticker=ticker, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed for {ticker}",
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not compute prediction for {ticker}",
        )

    response = PredictionResponse(
        ticker=result["ticker"],
        direction=result["direction"],
        confidence=result["confidence"],
        probabilities=result["probabilities"],
        model_version=result["model_version"],
        cached=False,
        predicted_at=datetime.now(timezone.utc),
    )

    # Cache in Redis (graceful degradation on Redis failure)
    try:
        if r is not None:
            await r.setex(
                cache_key,
                PREDICTION_CACHE_TTL,
                response.model_dump_json(exclude={"cached"}),
            )
    except Exception:
        logger.warning("redis_cache_write_failed", ticker=ticker)

    return response
