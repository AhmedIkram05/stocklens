"""
Pydantic schemas for market data endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.types import DecimalAsFloat


class OHLCVData(BaseModel):
    """Single day of OHLCV price data."""

    date: date
    open: Optional[DecimalAsFloat] = None
    high: Optional[DecimalAsFloat] = None
    low: Optional[DecimalAsFloat] = None
    close: Optional[DecimalAsFloat] = None
    adjusted_close: Optional[DecimalAsFloat] = None
    volume: Optional[int] = None
    # ponytail: all nullable — yfinance returns NaN for some fields on newly-listed tickers


class OHLCVResponse(BaseModel):
    ticker: str
    data: list[OHLCVData]
    total: int


class QuoteResponse(BaseModel):
    """Current quote snapshot for a single ticker."""

    ticker: str
    price: DecimalAsFloat
    change: DecimalAsFloat
    change_pct: DecimalAsFloat
    previous_close: DecimalAsFloat
    volume: int
    timestamp: datetime


class BatchQuoteResponse(BaseModel):
    quotes: list[QuoteResponse]
    total: int


# ── Query parameters ──

class OHLCVParams(BaseModel):
    """Query params for OHLCV endpoint."""
    start_date: Optional[date] = Field(
        None, description="Start date (inclusive). Defaults to 1 year ago."
    )
    end_date: Optional[date] = Field(None, description="End date (inclusive). Defaults to today.")
    # ponytail: no max_days limit for Phase 2 — add if abuse becomes an issue
