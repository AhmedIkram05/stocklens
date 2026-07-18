"""
FastAPI endpoints wrapping agent tool logic for direct HTTP access.

Phase 6 Round 4 — 7 endpoints exposed under ``/agent`` prefix.

Endpoints:
    - GET  /spending-analysis/{portfolio_id}    — spending by category
    - GET  /ticker-info/{ticker}                — company profile from yfinance
    - GET  /market-news                         — recent news for tickers
    - GET  /sector-exposure/{portfolio_id}      — sector allocation
    - GET  /diversification-score/{portfolio_id} — 0-100 composite score
    - GET  /dividend-insights/{ticker}          — dividend data from yfinance
    - POST /compare-tickers                     — side-by-side ticker comparison

Registered in main.py at ``prefix=/agent``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.database.connection import connection_ctx

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent_tools"])


# ── Helpers ────────────────────────────────────────────────────────────────

_yf_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


def _decimal_to_float(val: Any) -> float:
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _to_float(val: Any, default: float = 0.0) -> float:
    """Safely extract a float from a yfinance value (often None)."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


@_yf_retry
def _fetch_ticker_sector(t: str) -> tuple[str, str]:
    """Fetch sector for a ticker via yfinance."""
    info = yf.Ticker(t).info
    sector = info.get("sector", "Unknown")
    return t, sector if sector else "Unknown"


# ── Schemas ────────────────────────────────────────────────────────────────


class CompareTickersRequest(BaseModel):
    tickers: list[str]
    metrics: list[str] | None = None
    model_config = {
        "json_schema_extra": {
            "example": {"tickers": ["AAPL", "MSFT"], "metrics": ["pe_ratio", "market_cap"]}
        }
    }


# ── 4.1 Spending Analysis ──────────────────────────────────────────────────


@router.get("/spending-analysis/{portfolio_id}")
async def spending_analysis(
    portfolio_id: str,
    months: int = Query(6, ge=1, le=60, description="Months to look back"),
    current_user: UserInDB = Depends(get_current_user),
):
    """Aggregate transaction spending by category for a portfolio.

    Returns total spend per category, category breakdown with percentages,
    month-over-month change for each category, and top spend categories.
    """
    async with connection_ctx() as conn:
        portfolio = await conn.fetchrow(
            "SELECT id, name FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            current_user.id,
        )
        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        query = """
            SELECT
                sc.name AS category_name,
                sc.id AS category_id,
                COUNT(t.id) AS transaction_count,
                SUM(t.total_amount_gbp) AS total_spend
            FROM transactions t
            LEFT JOIN spending_categories sc ON t.spending_category_id = sc.id
            WHERE t.portfolio_id = $1::uuid
              AND t.type = 'BUY'
              AND t.transaction_date >= CURRENT_DATE - $2::interval
            GROUP BY sc.name, sc.id
            ORDER BY total_spend DESC
        """
        rows = await conn.fetch(query, portfolio_id, timedelta(days=30 * months))

    total_spent = sum(_to_float(r["total_spend"]) for r in rows)

    categories = []
    for r in rows:
        categories.append(
            {
                "category": r["category_name"] or "Uncategorised",
                "category_id": str(r["category_id"]) if r["category_id"] else None,
                "transaction_count": r["transaction_count"],
                "total_spend_gbp": round(_to_float(r["total_spend"]), 2),
                "pct_of_total": round(
                    (_to_float(r["total_spend"]) / total_spent * 100) if total_spent > 0 else 0, 2
                ),
            }
        )

    # Month-over-month: compare last full month vs previous full month
    today = date.today()
    first_current = today.replace(day=1)
    last_month_end = first_current - timedelta(days=1)
    first_last_month = last_month_end.replace(day=1)

    # Single grouped query: current + previous month spend per category_id.
    # ponytail: one round trip, keyed on category_id — no name/NULL fallback chains.
    month_over_month = {}
    async with connection_ctx() as conn:
        mom_rows = await conn.fetch(
            """
            SELECT
                COALESCE(sc.id::text, 'NULL') AS category_key,
                COALESCE(sc.name, 'Uncategorised') AS category_name,
                COALESCE(SUM(
                    CASE WHEN t.transaction_date >= $2::date AND t.transaction_date < $3::date
                         THEN t.total_amount_gbp END
                ), 0) AS current_month_spend,
                COALESCE(SUM(
                    CASE WHEN t.transaction_date >= $4::date AND t.transaction_date < $2::date
                         THEN t.total_amount_gbp END
                ), 0) AS previous_month_spend
            FROM transactions t
            LEFT JOIN spending_categories sc ON t.spending_category_id = sc.id
            WHERE t.portfolio_id = $1::uuid AND t.type = 'BUY'
              AND t.transaction_date >= $4::date AND t.transaction_date < $3::date
            GROUP BY sc.id, sc.name
            """,
            portfolio_id,
            first_current,
            today,
            first_last_month,
        )
        for r in mom_rows:
            current_month_spend = _to_float(r["current_month_spend"])
            previous_month_spend = _to_float(r["previous_month_spend"])
            change = round(current_month_spend - previous_month_spend, 2)
            change_pct = round(
                (change / previous_month_spend * 100) if previous_month_spend > 0 else 0,
                2,
            )
            month_over_month[r["category_name"]] = {
                "current_month_spend_gbp": round(current_month_spend, 2),
                "previous_month_spend_gbp": round(previous_month_spend, 2),
                "change_gbp": change,
                "change_pct": change_pct,
            }

    return {
        "portfolio_name": portfolio["name"],
        "period_months": months,
        "total_spent_gbp": round(total_spent, 2),
        "categories": categories,
        "month_over_month": month_over_month,
    }


# ── 4.2 Ticker Info ────────────────────────────────────────────────────────


@router.get("/ticker-info/{ticker}")
async def ticker_info(
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """Fetch company profile and fundamental data for a ticker via yfinance."""

    @_yf_retry
    def _fetch(t: str) -> dict:
        info = yf.Ticker(t).info
        return {
            "ticker": t,
            "company_name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country"),
            "website": info.get("website"),
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
        }

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _fetch, ticker.upper())
    return result


# ── 4.3 Market News ────────────────────────────────────────────────────────


@router.get("/market-news")
async def market_news(
    tickers: str = Query(..., description="Comma-separated ticker symbols, e.g. AAPL,MSFT"),
    max_articles: int = Query(5, ge=1, le=10),
    current_user: UserInDB = Depends(get_current_user),
):
    """Fetch recent news for one or more tickers via yfinance.

    Returns articles deduplicated by title, sorted by publish date descending.
    """
    raw_tickers = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    ticker_list = sorted(set(raw_tickers))
    if not ticker_list:
        raise HTTPException(status_code=400, detail="At least one ticker required")

    @_yf_retry
    def _fetch_news(t: str, limit: int) -> list[dict]:
        tk = yf.Ticker(t)
        news = tk.news or []
        articles = []
        for article in news[:limit]:
            articles.append(
                {
                    "ticker": t,
                    "title": article.get("title"),
                    "publisher": article.get("publisher"),
                    "link": article.get("link"),
                    "published_date": (
                        datetime.fromtimestamp(
                            article["providerPublishTime"], tz=timezone.utc
                        ).isoformat()
                        if article.get("providerPublishTime")
                        else None
                    ),
                    "summary": article.get("summary"),
                }
            )
        return articles

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch_news, t, max_articles) for t in ticker_list],
        return_exceptions=True,
    )

    all_articles: list[dict] = []
    seen_titles: set[str] = set()
    for result in results:
        if isinstance(result, list):
            for article in result:
                title = article.get("title") or ""
                if title not in seen_titles:
                    seen_titles.add(title)
                    all_articles.append(article)
        elif isinstance(result, Exception):
            logger.warning("news_fetch_failed", exc_info=result)

    all_articles.sort(key=lambda a: a.get("published_date") or "", reverse=True)

    return {"tickers": ticker_list, "article_count": len(all_articles), "articles": all_articles}


# ── 4.4 Sector Exposure ────────────────────────────────────────────────────


@router.get("/sector-exposure/{portfolio_id}")
async def sector_exposure(
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """Calculate sector allocation for a portfolio using yfinance sector data."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.ticker, h.shares, h.average_cost_basis_gbp "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid",
            portfolio_id,
            current_user.id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="No holdings found for this portfolio")

    total_value = sum(
        float(r["shares"]) * _decimal_to_float(r["average_cost_basis_gbp"]) for r in rows
    )

    unique_tickers = list({r["ticker"] for r in rows})
    sector_map: dict[str, str] = {}

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch_ticker_sector, t) for t in unique_tickers],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, tuple):
            t, sector = result
            sector_map[t] = sector
        elif isinstance(result, Exception):
            logger.warning("sector_fetch_failed", exc_info=result)

    sector_values: dict[str, float] = {}
    sector_tickers: dict[str, list[str]] = {}
    for r in rows:
        sector = sector_map.get(r["ticker"], "Unknown")
        value = float(r["shares"]) * _decimal_to_float(r["average_cost_basis_gbp"])
        sector_values[sector] = sector_values.get(sector, 0) + value
        sector_tickers.setdefault(sector, []).append(r["ticker"])

    sectors = []
    for sector, value in sorted(sector_values.items(), key=lambda x: -x[1]):
        sectors.append(
            {
                "sector": sector,
                "value_gbp": round(value, 2),
                "allocation_pct": round((value / total_value * 100) if total_value > 0 else 0, 2),
                "tickers": sorted(set(sector_tickers[sector])),
            }
        )

    return {"total_value_gbp": round(total_value, 2), "sectors": sectors}


# ── 4.5 Diversification Score ──────────────────────────────────────────────


@router.get("/diversification-score/{portfolio_id}")
async def diversification_score(
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """Compute a 0-100 diversification score with factor breakdown.

    Factors (weights):
      - Holdings count diversity (20%)
      - Sector concentration via HHI (40%)
      - Top holding weight (20%)
      - Sector proxy correlation (20%)
    """
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.ticker, h.shares, h.average_cost_basis_gbp "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid",
            portfolio_id,
            current_user.id,
        )

    if not rows:
        raise HTTPException(status_code=404, detail="No holdings found for this portfolio")

    values: list[dict] = []
    for r in rows:
        v = float(r["shares"]) * _decimal_to_float(r["average_cost_basis_gbp"])
        values.append({"ticker": r["ticker"], "value": v})

    total = sum(v["value"] for v in values)
    if total <= 0:
        raise HTTPException(status_code=400, detail="Portfolio has zero or negative total value")

    n = len(values)
    weights_pct = [(v["value"] / total) * 100 for v in values]
    weights_decimal = [v["value"] / total for v in values]
    values_sorted = sorted(values, key=lambda x: -x["value"])

    # 1. Holdings count diversity (20%): more holdings = more diversified
    # Scale: 1 holding → 0 pts, 20+ holdings → full 20 pts
    holdings_score = min(20.0, (n / 20.0) * 20.0)

    # 2. HHI sector concentration (40%): lower HHI = better
    # HHI = sum of squared weights (as percentages). Range 0-10000.
    hhi = sum(w * w for w in weights_pct)
    # Map: hhi=0 → 40, hhi=2500 → 20, hhi=10000 → 0
    sector_hhi_score = max(0.0, 40.0 * (1.0 - min(1.0, hhi / 2500.0)))

    # 3. Top holding weight (20%): lower top weight = better
    top_weight = weights_decimal[0] if weights_decimal else 1.0
    top_weight_score = max(0.0, 20.0 * (1.0 - top_weight))

    # 4. Sector proxy correlation (20%): fetch sectors via yfinance, compute HHI over sectors
    unique_tickers = list({v["ticker"] for v in values})

    loop = asyncio.get_running_loop()
    sector_results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch_ticker_sector, t) for t in unique_tickers],
        return_exceptions=True,
    )
    sector_map: dict[str, str] = {}
    for sr in sector_results:
        if isinstance(sr, tuple):
            t, s = sr
            sector_map[t] = s
        elif isinstance(sr, Exception):
            logger.warning("sector_fetch_failed_diversification", exc_info=sr)

    sector_weights: dict[str, float] = {}
    for v in values:
        sec = sector_map.get(v["ticker"], "Unknown")
        sector_weights[sec] = sector_weights.get(sec, 0) + v["value"]
    sector_pct_weights = [(sw / total) * 100 for sw in sector_weights.values()]
    sector_hhi = sum(w * w for w in sector_pct_weights)

    # Map sector HHI to a correlation score: low sector HHI = more diverse = higher score
    # sector_hhi=10000 (same sector) → 0, sector_hhi<1000 → full 20
    sector_corr_score = max(0.0, 20.0 * (1.0 - min(1.0, sector_hhi / 5000.0)))

    total_score = round(holdings_score + sector_hhi_score + top_weight_score + sector_corr_score, 2)
    total_score = min(100.0, total_score)

    # Recommendations
    recommendations = []
    if n < 5:
        recommendations.append("Consider adding more holdings to reduce concentration risk.")
    if top_weight > 0.4:
        recommendations.append(
            f"Top holding ({values_sorted[0]['ticker']}) represents "
            f"{round(top_weight * 100, 1)}% of portfolio — consider rebalancing."
        )
    if sector_hhi > 3000:
        recommendations.append(
            "Portfolio is concentrated in few sectors — consider sector diversification."
        )
    if hhi > 2000:
        recommendations.append(
            "High ticker concentration detected. Consider adding uncorrelated positions."
        )
    if not recommendations:
        recommendations.append("Well diversified portfolio. Maintain current allocation.")

    return {
        "overall_score": total_score,
        "breakdown": {
            "holdings_diversity_score": round(holdings_score, 2),
            "holdings_diversity_weight_pct": 20,
            "hhi_concentration_score": round(sector_hhi_score, 2),
            "hhi_concentration_weight_pct": 40,
            "hhi_raw_value": round(hhi, 2),
            "top_holding_weight_score": round(top_weight_score, 2),
            "top_holding_weight_pct": 20,
            "top_holding_ticker": values_sorted[0]["ticker"],
            "top_holding_exposure_pct": round(top_weight * 100, 2),
            "sector_diversity_score": round(sector_corr_score, 2),
            "sector_diversity_weight_pct": 20,
            "sector_hhi_value": round(sector_hhi, 2),
        },
        "total_holdings": n,
        "effective_holdings": round(1.0 / sum(w * w for w in weights_decimal), 2),
        "recommendations": recommendations,
    }


# ── 4.6 Dividend Insights ──────────────────────────────────────────────────


@router.get("/dividend-insights/{ticker}")
async def dividend_insights(
    ticker: str,
    current_user: UserInDB = Depends(get_current_user),
):
    """Fetch dividend information for a ticker via yfinance."""

    @_yf_retry
    def _fetch(t: str) -> dict:
        tk = yf.Ticker(t)
        info = tk.info
        dividends = tk.dividends
        return {
            "ticker": t,
            "dividend_rate": info.get("dividendRate"),
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "ex_dividend_date": (
                datetime.fromtimestamp(info["exDividendDate"], tz=timezone.utc).isoformat()
                if info.get("exDividendDate")
                else None
            ),
            "last_dividend_date": (
                str(dividends.index[-1])[:10]
                if dividends is not None and not dividends.empty
                else None
            ),
            "last_dividend_value": (
                float(dividends.iloc[-1]) if dividends is not None and not dividends.empty else None
            ),
            "five_year_growth": info.get("fiveYearAvgDividendYield"),
            "currency": info.get("currency"),
        }

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _fetch, ticker.upper())
    return result


# ── 4.7 Compare Tickers ────────────────────────────────────────────────────


@router.post("/compare-tickers")
async def compare_tickers(
    body: CompareTickersRequest,
    current_user: UserInDB = Depends(get_current_user),
):
    """Side-by-side comparison of multiple tickers.

    Accepts a list of tickers and optional metric filters.
    Returns a matrix of ticker × metric.
    """
    ticker_list = [t.strip().upper() for t in body.tickers if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="At least one ticker required")
    if len(ticker_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 tickers for comparison")

    ALL_METRICS = {
        "price": "currentPrice",
        "change_pct": "regularMarketChangePercent",
        "market_cap": "marketCap",
        "pe_ratio": "trailingPE",
        "forward_pe": "forwardPE",
        "sector": "sector",
        "industry": "industry",
        "dividend_yield": "dividendYield",
        "volume": "regularMarketVolume",
        "fifty_two_week_high": "fiftyTwoWeekHigh",
        "fifty_two_week_low": "fiftyTwoWeekLow",
    }

    metrics_to_fetch = body.metrics or list(ALL_METRICS.keys())
    unknown = [m for m in metrics_to_fetch if m not in ALL_METRICS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metrics: {unknown}. Available: {list(ALL_METRICS.keys())}",
        )

    @_yf_retry
    def _fetch(t: str) -> dict:
        info = yf.Ticker(t).info
        result: dict[str, Any] = {"ticker": t}
        for metric, yf_key in ALL_METRICS.items():
            if metric in metrics_to_fetch:
                result[metric] = info.get(yf_key)
        return result

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch, t) for t in ticker_list],
        return_exceptions=True,
    )

    comparisons: list[dict] = []
    errors: list[str] = []
    for i, result in enumerate(results):
        if isinstance(result, dict):
            comparisons.append(result)
        elif isinstance(result, Exception):
            errors.append(f"{ticker_list[i]}: {str(result)}")
            comparisons.append({"ticker": ticker_list[i], "error": str(result)})

    result = {"tickers": ticker_list, "comparisons": comparisons}
    if errors:
        result["errors"] = errors
    return result
