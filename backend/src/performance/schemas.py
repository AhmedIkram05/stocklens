"""
Pydantic schemas for portfolio performance and benchmark comparison endpoints.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from src.types import DecimalAsFloat


class HoldingPerformance(BaseModel):
    """Performance metrics for a single holding."""

    ticker: str
    shares: DecimalAsFloat
    average_cost_basis: DecimalAsFloat
    current_price: Optional[DecimalAsFloat] = None
    market_value: Optional[DecimalAsFloat] = None
    cost_basis: DecimalAsFloat
    unrealised_pl: Optional[DecimalAsFloat] = None
    unrealised_pl_pct: Optional[DecimalAsFloat] = None
    day_change: Optional[DecimalAsFloat] = None
    day_change_pct: Optional[DecimalAsFloat] = None
    portfolio_weight_pct: Optional[DecimalAsFloat] = None


class PortfolioPerformanceResponse(BaseModel):
    """Aggregate portfolio performance."""

    portfolio_id: str
    portfolio_name: str
    total_market_value: Optional[DecimalAsFloat] = None
    total_cost_basis: DecimalAsFloat
    total_unrealised_pl: Optional[DecimalAsFloat] = None
    total_unrealised_pl_pct: Optional[DecimalAsFloat] = None
    day_change: Optional[DecimalAsFloat] = None
    day_change_pct: Optional[DecimalAsFloat] = None
    free_cash_balance: DecimalAsFloat = Field(
        Decimal(0),
        description="Uninvested cash = SUM(deposits) - SUM(net BUY amounts)",
    )
    # Time-weighted return
    twr: Optional[DecimalAsFloat] = Field(None, description="Time-weighted return over the period")
    twr_annualised: Optional[DecimalAsFloat] = None
    twr_start_date: Optional[date] = None
    twr_end_date: Optional[date] = None
    twr_methodology: str = Field(
        "cash-flow-based",
        description="Cash flows are explicit deposits (from receipt scans); no manual withdrawals",
    )
    # Holdings breakdown
    holdings: list[HoldingPerformance]
    total_holdings: int
    # Data quality
    data_quality: str = Field(
        "complete",
        description="'complete' or 'partial' — partial means some holdings lack price data",
    )
    calculated_at: datetime


class BenchmarkComparisonResponse(BaseModel):
    """Portfolio vs benchmark comparison."""

    portfolio_id: str
    benchmark_ticker: str
    portfolio_return: Optional[DecimalAsFloat] = None
    benchmark_return: Optional[DecimalAsFloat] = None
    excess_return_alpha: Optional[DecimalAsFloat] = None
    tracking_error: Optional[DecimalAsFloat] = None
    information_ratio: Optional[DecimalAsFloat] = None
    period_start: date
    period_end: date
    methodology: str = "daily-linked"
    daily_returns_count: int = Field(0, description="Number of daily return observations used")
    calculated_at: datetime


class PerformanceParams(BaseModel):
    """Query parameters for performance endpoint."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    benchmark: Optional[str] = Field(None, description="Benchmark ticker (default: SPY)")


class BenchmarkParams(BaseModel):
    """Query parameters for benchmark comparison."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    benchmark: Optional[str] = Field("SPY", description="Benchmark ticker (SPY or QQQ)")
