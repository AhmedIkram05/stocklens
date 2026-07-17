"""
Agent tool definitions — 16 tools wrapping existing data sources.

Each tool is a LangGraph ``@tool`` async function.  The ``user_id`` parameter
is annotated with ``InjectedToolArg`` so the LLM never sees it — the service
injects it from ``AgentState``.

Categories: Portfolio (3), Performance (2), Analysis (2), Market Data (4),
Forecasting (1), Spending (3), Insights (1).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

import yfinance as yf
from langchain_core.tools import InjectedToolArg, tool

from src.database.connection import connection_ctx
from src.market.repository import get_ohlcv

logger = logging.getLogger(__name__)

# ── Shared helpers ───────────────────────────────────────────────────────


def _decimal_to_float(val: Any) -> float:
    """Convert Decimal (or any numeric) to float for JSON serialisation."""
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Portfolio tools (3)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_portfolio_summary(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch a portfolio's summary: name, description, total value, cash balance, created date.

    Use this when the user asks "How's my portfolio?", "What's my portfolio worth?",
    or "Show me my portfolio overview".
    Returns: name, description, total_market_value, free_cash_balance, total_cost_basis,
    unrealised_pl, created_at.
    Limitations: Does NOT include per-holding breakdown or return percentages.
    Complementary tools: get_portfolio_holdings (for per-holding details),
    get_portfolio_performance (for return percentages over time).
    """
    async with connection_ctx() as conn:
        # Fetch portfolio metadata
        portfolio = await conn.fetchrow(
            "SELECT id, name, description, created_at FROM portfolios "
            "WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
        if not portfolio:
            return json.dumps({"error": "Portfolio not found"})

        # Fetch holdings (ticker + shares + cost basis + fx) for market-value calc
        holdings_rows = await conn.fetch(
            "SELECT ticker, shares, average_cost_basis_gbp, "
            "COALESCE(fx_rate_to_gbp, 1) AS fx_rate_to_gbp "
            "FROM holdings WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )

        # Fetch free cash balance from cash_flows - transactions
        cash_in = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
        buys = await conn.fetchval(
            "SELECT COALESCE(SUM(total_amount_gbp), 0) FROM transactions "
            "WHERE portfolio_id = $1::uuid AND type = 'BUY'",
            portfolio_id,
        )
        sells = await conn.fetchval(
            "SELECT COALESCE(SUM(total_amount_gbp), 0) FROM transactions "
            "WHERE portfolio_id = $1::uuid AND type = 'SELL'",
            portfolio_id,
        )
        free_cash = Decimal(str(cash_in or 0)) - Decimal(str(buys or 0)) + Decimal(str(sells or 0))

        holding_count = len(holdings_rows)

    # Compute cost basis + market value from live quotes (fallback to cost basis)
    from src.market.provider import fetch_quote as _fetch_quote

    async def _q(t: str) -> tuple[str, Decimal | None]:
        try:
            q = await _fetch_quote(t)
            return t, Decimal(str(q["price"]))
        except Exception:
            return t, None

    live_prices: dict[str, Decimal] = {}
    if holdings_rows:
        for r in await asyncio.gather(
            *[_q(h["ticker"]) for h in holdings_rows], return_exceptions=True
        ):
            if isinstance(r, tuple) and r[1] is not None:
                live_prices[r[0]] = r[1]

    total_cost_basis = Decimal(0)
    total_market_value = Decimal(0)
    for h in holdings_rows:
        shares = Decimal(str(h["shares"]))
        fx = Decimal(str(h["fx_rate_to_gbp"]))
        cost = Decimal(str(h["average_cost_basis_gbp"])) * shares
        total_cost_basis += cost
        price = live_prices.get(h["ticker"])
        if price is not None:
            total_market_value += price * fx * shares
        else:
            total_market_value += cost

    unrealised_pl = total_market_value - total_cost_basis

    result = {
        "portfolio_id": str(portfolio["id"]),
        "name": portfolio["name"],
        "description": portfolio["description"],
        "holding_count": holding_count,
        "total_market_value_gbp": _decimal_to_float(total_market_value),
        "free_cash_balance_gbp": _decimal_to_float(free_cash),
        "total_cost_basis_gbp": _decimal_to_float(total_cost_basis),
        "unrealised_pl_gbp": _decimal_to_float(unrealised_pl),
        "created_at": portfolio["created_at"].isoformat() if portfolio["created_at"] else None,
    }
    return json.dumps(result, default=str)


@tool
async def get_portfolio_holdings(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch current holdings for a portfolio.

    Use this when the user asks about what they own, their positions,
    "What are my holdings?", or portfolio composition.
    Returns: per-holding ticker, shares, average_cost_basis, market_value,
    unrealised_pl, portfolio_weight_pct, currency.
    Limitations: Does NOT include return percentages or benchmarks.
    Complementary tools: get_portfolio_summary (for portfolio-level overview),
    get_portfolio_performance (for return percentages).
    """
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.id, h.ticker, h.shares, h.average_cost_basis, "
            "h.currency, h.average_cost_basis_gbp "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid "
            "ORDER BY h.ticker",
            portfolio_id,
            user_id,
        )

    holdings_list = []
    for r in rows:
        holdings_list.append(
            {
                "ticker": r["ticker"],
                "shares": float(r["shares"]),
                "average_cost_basis": _decimal_to_float(r["average_cost_basis"]),
                "currency": r.get("currency", "GBP"),
                "average_cost_basis_gbp": _decimal_to_float(r.get("average_cost_basis_gbp", 0)),
            }
        )

    if not holdings_list:
        return json.dumps({"holdings": [], "total": 0})

    return json.dumps({"holdings": holdings_list, "total": len(holdings_list)}, default=str)


@tool
async def get_sector_exposure(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Calculate sector exposure breakdown for a portfolio using yfinance sector data.

    Use this when the user asks "What sectors am I invested in?",
    "How is my portfolio diversified by sector?", or "Sector allocation".
    Returns: per-sector name, percentage of portfolio, and constituent tickers.
    Limitations: Sector data comes from yfinance and may be unavailable for some tickers.
    Tickers with no sector data are grouped under "Unknown".
    Complementary tools: get_portfolio_diversification_score (for overall score).
    """
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.ticker, h.shares, h.average_cost_basis_gbp "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid",
            portfolio_id,
            user_id,
        )

    if not rows:
        return json.dumps({"error": "No holdings found for this portfolio"})

    # Calculate total value
    total_value = sum(
        float(r["shares"]) * _decimal_to_float(r["average_cost_basis_gbp"]) for r in rows
    )

    # Fetch sector for each unique ticker from yfinance
    unique_tickers = list({r["ticker"] for r in rows})
    sector_map: dict[str, str] = {}

    def _fetch_sector(t: str) -> tuple[str, str]:
        try:
            info = yf.Ticker(t).info
            sector = info.get("sector", "Unknown")
            return t, sector if sector else "Unknown"
        except Exception:
            return t, "Unknown"

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch_sector, t) for t in unique_tickers],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, tuple):
            t, sector = result
            sector_map[t] = sector
        elif isinstance(result, Exception):
            logger.warning("sector_fetch_failed", exc_info=result)

    # Aggregate by sector
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

    return json.dumps({"total_value_gbp": round(total_value, 2), "sectors": sectors}, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Performance tools (2)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_portfolio_performance(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
    include_history: bool = False,
) -> str:
    """Fetch portfolio performance metrics including TWR, daily returns, and optional history.

    Use this when the user asks "What's my return?", "How did I perform last quarter?",
    "What is my portfolio performance?", or "Show me my gains and losses".
    Returns: twr, twr_annualised, total_gain_loss, total_gain_loss_pct, periods.
    When include_history=True: also returns daily return time series.
    Does NOT include: current value snapshot (use get_portfolio_summary).
    Complementary tools: get_portfolio_summary (for current value snapshot),
    compare_to_benchmark (for benchmark comparison).
    """
    from datetime import date as _date
    from decimal import Decimal as _Decimal

    from src.market.provider import fetch_quote as _fetch_quote
    from src.market.repository import get_ohlcv_batch as _get_ohlcv_batch
    from src.performance.calculations import compute_portfolio_performance

    async with connection_ctx() as conn:
        portfolio = await conn.fetchrow(
            "SELECT id, name FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
        if not portfolio:
            return json.dumps({"error": "Portfolio not found"})

        holdings_rows = await conn.fetch(
            "SELECT id, ticker, shares, average_cost_basis, "
            "average_cost_basis_gbp, currency, fx_rate_to_gbp "
            "FROM holdings WHERE portfolio_id = $1::uuid "
            "ORDER BY ticker",
            portfolio_id,
        )

        transaction_rows = await conn.fetch(
            "SELECT id, ticker, type, shares, price_per_share, total_amount, "
            "total_amount_gbp, transaction_date "
            "FROM transactions WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date ASC, created_at ASC, id ASC",
            portfolio_id,
        )

        cash_flow_rows = await conn.fetch(
            "SELECT amount, created_at FROM cash_flows "
            "WHERE portfolio_id = $1::uuid ORDER BY created_at ASC",
            portfolio_id,
        )

    if not holdings_rows:
        return json.dumps(
            {
                "portfolio_name": portfolio["name"],
                "total_cost_basis": 0,
                "total_market_value": 0,
                "holdings": [],
                "total_holdings": 0,
            }
        )

    # Assemble data structures for the calculator
    holdings_data = [dict(r) for r in holdings_rows]

    transactions = []
    for r in transaction_rows:
        d = dict(r)
        d["date"] = d.pop("transaction_date")
        transactions.append(d)

    cf_list = [dict(r) for r in cash_flow_rows]

    from datetime import timedelta as _timedelta

    end = _date.today()
    start = end - _timedelta(days=365)

    tickers = list({h["ticker"] for h in holdings_data})
    try:
        batch_results = await _get_ohlcv_batch(tickers, start_date=start, end_date=end, limit=50000)
    except Exception:
        batch_results = {}

    price_map: dict[str, dict[_date, _Decimal]] = {}
    for ticker in tickers:
        rows = batch_results.get(ticker, [])
        price_map[ticker] = {
            r["date"]: r["adjusted_close"] for r in rows if r["adjusted_close"] is not None
        }

    # Live quotes
    async def _q(t: str) -> tuple[str, tuple[_Decimal, _Decimal] | None]:
        try:
            q = await _fetch_quote(t)
            return t, (q["price"], q["previous_close"])
        except Exception:
            return t, None

    live_quotes: dict[str, tuple[_Decimal, _Decimal]] = {}
    for r in await asyncio.gather(*[_q(t) for t in tickers], return_exceptions=True):
        if isinstance(r, tuple) and r[1] is not None:
            live_quotes[r[0]] = r[1]

    fx_rates = {h["ticker"]: (h.get("fx_rate_to_gbp") or _Decimal(1)) for h in holdings_data}

    try:
        result = compute_portfolio_performance(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio["name"],
            holdings_data=holdings_data,
            transactions=transactions,
            cash_flows=cf_list,
            price_map=price_map,
            start_date=start,
            end_date=end,
            enable_twr=True,
            live_quotes=live_quotes or None,
            fx_rates=fx_rates,
        )
        return json.dumps(
            {
                "portfolio_name": portfolio["name"],
                **dict(result),
            },
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": f"Performance calculation failed: {e}"}, default=str)


@tool
async def compare_to_benchmark(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
    benchmark_ticker: str = "SPY",
) -> str:
    """Compare portfolio performance against a benchmark index (SPY, QQQ, etc.).

    Use this when the user asks "How am I doing vs the market?",
    "Compare my portfolio to SPY", "What is my alpha?", or "Am I beating the market?".
    Returns: portfolio_return, benchmark_return, excess_return_alpha, tracking_error,
    information_ratio, benchmark_ticker, period.
    Limitations: Requires sufficient OHLCV data for both portfolio and benchmark.
    Complementary tools: get_portfolio_performance (for standalone returns).
    """
    from datetime import date as _date
    from datetime import timedelta as _timedelta
    from decimal import Decimal as _Decimal

    from src.market.provider import fetch_quote as _fetch_quote
    from src.market.repository import get_ohlcv_batch as _get_ohlcv_batch
    from src.performance.calculations import (
        compute_benchmark_comparison,
        compute_portfolio_performance,
    )

    async with connection_ctx() as conn:
        portfolio = await conn.fetchrow(
            "SELECT id, name FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
        if not portfolio:
            return json.dumps({"error": "Portfolio not found"})

        holdings_rows = await conn.fetch(
            "SELECT id, ticker, shares, average_cost_basis, "
            "average_cost_basis_gbp, currency, fx_rate_to_gbp "
            "FROM holdings WHERE portfolio_id = $1::uuid "
            "ORDER BY ticker",
            portfolio_id,
        )

        transaction_rows = await conn.fetch(
            "SELECT id, ticker, type, shares, price_per_share, total_amount, "
            "total_amount_gbp, transaction_date "
            "FROM transactions WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date ASC, created_at ASC, id ASC",
            portfolio_id,
        )

        cash_flow_rows = await conn.fetch(
            "SELECT amount, created_at FROM cash_flows "
            "WHERE portfolio_id = $1::uuid ORDER BY created_at ASC",
            portfolio_id,
        )

    if not holdings_rows:
        return json.dumps({"error": "No holdings in portfolio", "benchmark": benchmark_ticker})

    holdings_data = [dict(r) for r in holdings_rows]
    transactions = []
    for r in transaction_rows:
        d = dict(r)
        d["date"] = d.pop("transaction_date")
        transactions.append(d)
    cf_list = [dict(r) for r in cash_flow_rows]

    end = _date.today()
    start = end - _timedelta(days=365)

    all_tickers = list({h["ticker"] for h in holdings_data} | {benchmark_ticker})
    try:
        batch_results = await _get_ohlcv_batch(
            all_tickers, start_date=start, end_date=end, limit=50000
        )
    except Exception:
        batch_results = {}

    price_map: dict[str, dict[_date, _Decimal]] = {}
    for ticker in all_tickers:
        rows = batch_results.get(ticker, [])
        price_map[ticker] = {
            r["date"]: r["adjusted_close"] for r in rows if r["adjusted_close"] is not None
        }

    if not price_map.get(benchmark_ticker):
        return json.dumps({"error": f"No price data for benchmark {benchmark_ticker}"})

    # Live quotes
    async def _q(t: str) -> tuple[str, tuple[_Decimal, _Decimal] | None]:
        try:
            q = await _fetch_quote(t)
            return t, (q["price"], q["previous_close"])
        except Exception:
            return t, None

    live_quotes: dict[str, tuple[_Decimal, _Decimal]] = {}
    for r in await asyncio.gather(
        *[_q(h["ticker"]) for h in holdings_data], return_exceptions=True
    ):
        if isinstance(r, tuple) and r[1] is not None:
            live_quotes[r[0]] = r[1]

    fx_rates = {h["ticker"]: (h.get("fx_rate_to_gbp") or _Decimal(1)) for h in holdings_data}

    try:
        # 1. Compute portfolio performance to get TWR
        perf_response = compute_portfolio_performance(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio["name"],
            holdings_data=holdings_data,
            transactions=transactions,
            cash_flows=cf_list,
            price_map=price_map,
            start_date=start,
            end_date=end,
            enable_twr=True,
            live_quotes=live_quotes or None,
            fx_rates=fx_rates,
        )
    except Exception as e:
        return json.dumps({"error": f"Performance calculation failed: {e}"})

    # 2. Compute benchmark daily returns from price data
    benchmark_prices = price_map.get(benchmark_ticker, {})
    benchmark_dates = sorted(benchmark_prices.keys())
    benchmark_daily_returns = []
    for i in range(1, len(benchmark_dates)):
        prev_p = benchmark_prices[benchmark_dates[i - 1]]
        curr_p = benchmark_prices[benchmark_dates[i]]
        if prev_p > 0:
            benchmark_daily_returns.append((curr_p - prev_p) / prev_p)

    # 3. Compute portfolio daily returns
    from collections import defaultdict

    portfolio_dates_list: list[_date] = []
    portfolio_daily_returns_list: list[_Decimal] = []

    all_price_dates: set[_date] = set()
    for tp in price_map.values():
        all_price_dates.update(tp.keys())
    if all_price_dates:
        trading_days = sorted(d for d in all_price_dates if start <= d <= end)
        if len(trading_days) >= 2:
            txns_by_date: dict[_date, list[dict]] = defaultdict(list)
            for t in transactions:
                date_key = t.get("date") or t.get("transaction_date")
                if date_key:
                    txns_by_date[date_key].append(t)

            current_shares: dict[str, _Decimal] = {}
            previous_value = _Decimal(0)

            for i, day in enumerate(trading_days):
                for txn in txns_by_date.get(day, []):
                    ticker = txn["ticker"]
                    if txn["type"] == "BUY":
                        cur = current_shares.get(ticker, _Decimal(0))
                        current_shares[ticker] = cur + txn["shares"]
                    elif txn["type"] == "SELL":
                        cur = current_shares.get(ticker, _Decimal(0))
                        current_shares[ticker] = cur - txn["shares"]
                        if current_shares[ticker] <= 0:
                            del current_shares[ticker]

                value = _Decimal(0)
                for ticker, shares in current_shares.items():
                    tp = price_map.get(ticker, {})
                    # Use live intraday price on the final day when available
                    # (mirrors compute_portfolio_performance's live_quotes override)
                    if i == len(trading_days) - 1 and ticker in live_quotes:
                        px = live_quotes[ticker][0]
                    elif day in tp and tp[day] is not None:
                        px = tp[day]
                    else:
                        continue
                    fx = fx_rates.get(ticker, _Decimal(1))
                    value += shares * px * fx

                if i > 0 and previous_value > 0:
                    portfolio_daily_returns_list.append((value - previous_value) / previous_value)
                    portfolio_dates_list.append(day)

                previous_value = value

    try:
        comparison = compute_benchmark_comparison(
            portfolio_id=portfolio_id,
            portfolio_twr=perf_response.twr,
            benchmark_ticker=benchmark_ticker,
            benchmark_daily_returns=benchmark_daily_returns,
            portfolio_daily_returns=portfolio_daily_returns_list,
            period_start=start,
            period_end=end,
        )
        return json.dumps(
            {
                "portfolio_name": portfolio["name"],
                "benchmark_ticker": benchmark_ticker,
                "portfolio_return": (float(perf_response.twr) if perf_response.twr else None),
                "benchmark_return": (
                    float(comparison.benchmark_return) if comparison.benchmark_return else None
                ),
                "excess_return_alpha": (
                    float(comparison.excess_return_alpha)
                    if comparison.excess_return_alpha
                    else None
                ),
                "tracking_error": (
                    float(comparison.tracking_error) if comparison.tracking_error else None
                ),
                "information_ratio": (
                    float(comparison.information_ratio) if comparison.information_ratio else None
                ),
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "daily_returns_count": comparison.daily_returns_count,
            },
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": f"Benchmark comparison failed: {e}"}, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Analysis tools (2)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_portfolio_diversification_score(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Calculate portfolio diversification using the Herfindahl-Hirschman Index (HHI).

    Use this when the user asks "How diversified is my portfolio?",
    "What is my concentration risk?", or "Diversification score".
    Returns: hhi_score (0-10000), concentration_level (low/moderate/high),
    effective_holdings (diversification-equivalent count), ticker_exposures.
    Lower HHI = more diversified. HHI < 1000 = well diversified.
    This is the top differentiator for the agent.
    Complementary tools: get_sector_exposure (for sector-level diversification).
    """
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.ticker, h.shares, h.average_cost_basis_gbp "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid",
            portfolio_id,
            user_id,
        )

    if not rows:
        return json.dumps({"error": "No holdings found for this portfolio"})

    # Calculate total value and weights
    values = []
    for r in rows:
        value = float(r["shares"]) * _decimal_to_float(r["average_cost_basis_gbp"])
        values.append({"ticker": r["ticker"], "value": value})

    total = sum(v["value"] for v in values)
    if total <= 0:
        return json.dumps({"error": "Portfolio has zero or negative total value"})

    # HHI = sum of squared weights (as percentages) * 10000
    weights_pct = [(v["value"] / total) * 100 for v in values]
    hhi = sum(w * w for w in weights_pct)  # /100 normalization: HHI range 0-10000

    if hhi < 1000:
        level = "low"
    elif hhi < 2500:
        level = "moderate"
    else:
        level = "high"

    # Effective holdings = 1 / sum(weight^2) where weights are in decimal
    weights_decimal = [v["value"] / total for v in values]
    effective_holdings = 1.0 / sum(w * w for w in weights_decimal) if total > 0 else 1

    ticker_exposures = [
        {"ticker": v["ticker"], "exposure_pct": round((v["value"] / total) * 100, 2)}
        for v in sorted(values, key=lambda x: -x["value"])
    ]

    return json.dumps(
        {
            "hhi_score": round(hhi, 2),
            "concentration_level": level,
            "effective_holdings": round(effective_holdings, 2),
            "total_holdings": len(values),
            "ticker_exposures": ticker_exposures,
        },
        default=str,
    )


@tool
async def compare_tickers_side_by_side(
    tickers: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Compare multiple tickers side-by-side: price, YTD change, market cap, sector, PE.

    Use this when the user asks "Compare AAPL and MSFT", "How do these stocks compare?",
    "Side by side comparison of ...", or "Which stock is better?".
    Accepts comma-separated tickers (e.g. "AAPL,MSFT,GOOGL").
    Returns: per-ticker price, change_pct, market_cap, pe_ratio, sector, dividend_yield.
    Limitations: Data from yfinance — may be stale for after-hours / weekends.
    Complementary tools: get_market_quote (for a single ticker quote).
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No valid tickers provided"})
    if len(ticker_list) > 10:
        return json.dumps({"error": "Maximum 10 tickers for side-by-side comparison"})

    def _fetch_info(t: str) -> dict:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            return {
                "ticker": t,
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "change_pct": info.get("regularMarketChangePercent"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "dividend_yield": info.get("dividendYield"),
                "volume": info.get("regularMarketVolume"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            }
        except Exception as e:
            return {"ticker": t, "error": str(e)}

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _fetch_info, t) for t in ticker_list],
        return_exceptions=True,
    )

    comparisons = []
    for result in results:
        if isinstance(result, dict):
            comparisons.append(result)
        elif isinstance(result, Exception):
            comparisons.append({"error": str(result)})

    return json.dumps({"tickers": comparisons}, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Market Data tools (4)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_market_ohlcv(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch historical OHLCV (Open, High, Low, Close, Volume) data for a ticker.

    Use this when the user asks "Show me price history for AAPL",
    "What was TSLA's price last month?", or "Historical data for ...".
    Returns: list of {date, open, high, low, close, adjusted_close, volume}.
    Limitations: Data from cached ohlcv_prices table — may not include today.
    Complementary tools: get_market_quote (for current price).
    """
    try:
        start = date.fromisoformat(start_date) if start_date else None
        end = date.fromisoformat(end_date) if end_date else None
    except (ValueError, TypeError):
        return json.dumps({"error": "Invalid date format. Use YYYY-MM-DD."})

    try:
        rows = await get_ohlcv(ticker.upper(), start_date=start, end_date=end)
        return json.dumps(
            {"ticker": ticker.upper(), "data_points": len(rows), "ohlcv": rows}, default=str
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch OHLCV: {e}"}, default=str)


@tool
async def get_market_quote(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Get a real-time (cached up to 60s) price quote for a ticker.

    Use this when the user asks "What's the current price of AAPL?",
    "AAPL stock price", "Quote for MSFT", or "How much is ... trading at?".
    Returns: ticker, price, change, change_pct, previous_close, volume, timestamp.
    Limitations: Quote cached for 60 seconds in Redis. After-hours data may
    reflect previous close.
    Complementary tools: get_market_ohlcv (for historical data),
    get_ticker_info (for company profile).
    """
    from src.market.provider import fetch_quote

    try:
        quote = await fetch_quote(ticker.upper())
        if not quote:
            return json.dumps({"error": f"No quote data available for {ticker.upper()}"})
        return json.dumps(dict(quote), default=str)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch quote: {e}"}, default=str)


@tool
async def get_ticker_info(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch comprehensive company profile and financial info for a ticker.

    Use this when the user asks "Tell me about AAPL", "Company profile for MSFT",
    "What does this company do?", or "Ticker info for ...".
    Returns: company_name, sector, industry, description, market_cap, pe_ratio,
    dividend_yield, fifty_two_week_range, employees, country, website.
    Limitations: Data from yfinance — may be stale. Not all fields available for all tickers.
    Complementary tools: get_market_quote (for current price),
    compare_tickers_side_by_side (for multi-ticker comparison).
    """

    def _fetch_info(t: str) -> dict:
        try:
            tk = yf.Ticker(t)
            info = tk.info
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
        except Exception as e:
            return {"ticker": t, "error": str(e)}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _fetch_info, ticker.upper())
    return json.dumps(result, default=str)


@tool
async def get_market_news(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
    max_articles: int = 5,
) -> str:
    """Fetch recent news articles for a ticker from Yahoo Finance.

    Use this when the user asks "Any news on AAPL?", "What's happening with TSLA?",
    "Recent news for MSFT", or "Why is ... moving?".
    ⚠️ Limitations: yfinance news is limited and may be stale. Returns at most
    max_articles articles (default 5, max 10). For serious news, use a dedicated service.
    Returns: list of {title, publisher, link, published_date, summary}.
    Complementary tools: get_ticker_info (for company profile), get_market_quote (for price).
    """
    if max_articles < 1:
        max_articles = 1
    if max_articles > 10:
        max_articles = 10

    def _fetch_news(t: str, limit: int) -> list:
        try:
            tk = yf.Ticker(t)
            news = tk.news or []
            articles = []
            for article in news[:limit]:
                articles.append(
                    {
                        "title": article.get("title"),
                        "publisher": article.get("publisher"),
                        "link": article.get("link"),
                        "published_date": (
                            datetime.fromtimestamp(
                                article.get("providerPublishTime", 0), tz=timezone.utc
                            ).isoformat()
                            if article.get("providerPublishTime")
                            else None
                        ),
                        "summary": article.get("summary"),
                    }
                )
            return articles
        except Exception as e:
            return [{"error": str(e)}]

    loop = asyncio.get_running_loop()
    articles = await loop.run_in_executor(None, _fetch_news, ticker.upper(), max_articles)
    return json.dumps({"ticker": ticker.upper(), "articles": articles}, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Forecasting tools (1)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_lstm_forecast(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch the LSTM directional forecast (UP/FLAT/DOWN) for a ticker.

    Use this when the user asks "What's the forecast for AAPL?",
    "Will TSLA go up?", "Prediction for MSFT", or "LSTM forecast for ...".
    Returns: ticker, prediction (UP/FLAT/DOWN), confidence, probabilities,
    model_version.
    Limitations: The LSTM model has ~53% directional accuracy — use as one
    signal among many. Not available for all tickers.
    Complementary tools: get_ticker_info (for company profile),
    get_market_ohlcv (for price history).
    """
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    from src.market.repository import get_ohlcv as _get_ohlcv
    from src.prediction.service import prediction_service

    try:
        end = _date.today()
        start = end - _timedelta(days=365)
        ohlcv_rows = await _get_ohlcv(ticker.upper(), start_date=start, end_date=end, limit=500)
        if not ohlcv_rows:
            return json.dumps({"error": f"No OHLCV data for {ticker.upper()}"})

        result = prediction_service.predict(ticker.upper(), ohlcv_rows=ohlcv_rows)
        if not result:
            return json.dumps({"error": f"No forecast available for {ticker.upper()}"})
        return json.dumps(dict(result), default=str)
    except Exception as e:
        return json.dumps({"error": f"Forecast failed: {e}"}, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Spending tools (3)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_spending_analysis(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Analyse spending patterns: total spent, category breakdown, and trends.

    Use this when the user asks "Where is my money going?", "Spending analysis",
    "How much did I spend on ...?", or "Category breakdown of my spending".
    Returns: total_spent, transaction_count, category_breakdown (name, amount, count, pct),
    period covered.
    Limitations: Only covers transactions linked to this portfolio. Categories
    are derived from spending_category_id on transactions.
    Complementary tools: get_recent_transactions (for individual transaction details),
    get_cash_flow_summary (for deposit/withdrawal patterns).
    """
    try:
        start = date.fromisoformat(start_date) if start_date else date(2000, 1, 1)
        end = date.fromisoformat(end_date) if end_date else date.today()
    except (ValueError, TypeError):
        return json.dumps({"error": "Invalid date format. Use YYYY-MM-DD."})

    async with connection_ctx() as conn:
        # Verify ownership
        portfolio = await conn.fetchrow(
            "SELECT id, name FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
        if not portfolio:
            return json.dumps({"error": "Portfolio not found"})

        rows = await conn.fetch(
            "SELECT t.ticker, t.type, t.total_amount_gbp, t.transaction_date, "
            "t.spending_category_id, sc.name AS category_name "
            "FROM transactions t "
            "LEFT JOIN spending_categories sc ON sc.id = t.spending_category_id "
            "WHERE t.portfolio_id = $1::uuid "
            "AND t.transaction_date >= $2::date "
            "AND t.transaction_date <= $3::date "
            "ORDER BY t.transaction_date DESC",
            portfolio_id,
            start,
            end,
        )

    total_spent = sum(float(r["total_amount_gbp"] or 0) for r in rows if r["type"] == "BUY")
    total_received = sum(float(r["total_amount_gbp"] or 0) for r in rows if r["type"] == "SELL")

    # Category breakdown — derived from the same BUY population as total_spent
    # so percentages reconcile (SELL proceeds are reported separately above).
    categories: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["type"] != "BUY":
            continue
        cat_name = r["category_name"] or "Uncategorised"
        if cat_name not in categories:
            categories[cat_name] = {"amount": 0.0, "count": 0}
        categories[cat_name]["amount"] += float(r["total_amount_gbp"] or 0)
        categories[cat_name]["count"] += 1

    category_breakdown = [
        {
            "name": name,
            "amount_gbp": round(data["amount"], 2),
            "count": data["count"],
            "pct_of_total": round(
                (data["amount"] / total_spent * 100) if total_spent > 0 else 0, 2
            ),
        }
        for name, data in sorted(categories.items(), key=lambda x: -x[1]["amount"])
    ]

    return json.dumps(
        {
            "portfolio_name": portfolio["name"],
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "total_spent_gbp": round(total_spent, 2),
            "total_received_gbp": round(total_received, 2),
            "transaction_count": len(rows),
            "category_breakdown": category_breakdown,
        },
        default=str,
    )


@tool
async def get_recent_transactions(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
    limit: int = 10,
) -> str:
    """Fetch recent transactions for a portfolio.

    Use this when the user asks "Show my recent trades", "What did I buy recently?",
    "Recent transactions for ...", or "Latest activity".
    Returns: per-transaction ticker, type (BUY/SELL), shares, price, total_amount,
    transaction_date, notes.
    Limitations: Max 100 transactions per query. Ordered by date DESC.
    Complementary tools: get_spending_analysis (for category breakdown),
    get_cash_flow_summary (for deposits).
    """
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT t.id, t.ticker, t.type, t.shares, t.price_per_share, "
            "t.total_amount, t.total_amount_gbp, t.transaction_date, t.notes, "
            "t.created_at "
            "FROM transactions t "
            "JOIN portfolios p ON p.id = t.portfolio_id "
            "WHERE t.portfolio_id = $1::uuid AND p.user_id = $2::uuid "
            "ORDER BY t.transaction_date DESC, t.created_at DESC "
            "LIMIT $3",
            portfolio_id,
            user_id,
            limit,
        )

    transactions = []
    for r in rows:
        transactions.append(
            {
                "id": str(r["id"]),
                "ticker": r["ticker"],
                "type": r["type"],
                "shares": float(r["shares"]),
                "price_per_share": _decimal_to_float(r["price_per_share"]),
                "total_amount": _decimal_to_float(r["total_amount"]),
                "total_amount_gbp": _decimal_to_float(r.get("total_amount_gbp", 0)),
                "date": r["transaction_date"].isoformat() if r["transaction_date"] else None,
                "notes": r["notes"],
            }
        )

    return json.dumps({"transactions": transactions, "total": len(transactions)}, default=str)


@tool
async def get_cash_flow_summary(
    portfolio_id: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch cash flow summary: deposits into a portfolio over time.

    Use this when the user asks "How much money have I deposited?",
    "Cash flow summary", "Deposit history", or "What have I put into this portfolio?".
    Returns: total_deposits, deposit_count, most_recent_deposit, deposits_by_source.
    Limitations: Shows deposits only (no withdrawals — not supported in v1).
    Does NOT include current cash balance (use get_portfolio_summary).
    Complementary tools: get_portfolio_summary (for current cash balance),
    get_recent_transactions (for trade activity).
    """
    async with connection_ctx() as conn:
        portfolio = await conn.fetchrow(
            "SELECT id, name FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
        if not portfolio:
            return json.dumps({"error": "Portfolio not found"})

        rows = await conn.fetch(
            "SELECT amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at DESC",
            portfolio_id,
        )

    total = sum(float(r["amount"]) for r in rows)
    counts_by_source: dict[str, int] = {}
    for r in rows:
        source = r["source"] or "manual"
        counts_by_source[source] = counts_by_source.get(source, 0) + 1

    deposits_by_source = [
        {"source": source, "count": count} for source, count in sorted(counts_by_source.items())
    ]

    most_recent = rows[0] if rows else None

    return json.dumps(
        {
            "portfolio_name": portfolio["name"],
            "total_deposits_gbp": round(total, 2),
            "deposit_count": len(rows),
            "most_recent_deposit": {
                "amount": float(most_recent["amount"]) if most_recent else None,
                "date": most_recent["created_at"].isoformat() if most_recent else None,
            }
            if most_recent
            else None,
            "deposits_by_source": deposits_by_source,
        },
        default=str,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Insights tools (1)
# ═══════════════════════════════════════════════════════════════════════════


@tool
async def get_dividend_insights(
    ticker: str,
    user_id: Annotated[str, InjectedToolArg],
) -> str:
    """Fetch dividend information for a ticker: yield, rate, payout ratio, ex-dividend date.

    Use this when the user asks "Does AAPL pay dividends?",
    "What's the dividend yield for MSFT?", "Dividend info for ...",
    or "When is the next dividend for ...?".
    Returns: dividend_rate, dividend_yield, payout_ratio, ex_dividend_date,
    last_dividend_date, five_year_growth.
    Limitations: Data from yfinance. Not all fields available for all tickers.
    Non-dividend stocks will return empty fields.
    Complementary tools: get_ticker_info (for full company profile).
    """

    def _fetch_dividend(t: str) -> dict:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            dividends = tk.dividends

            result = {
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
                    float(dividends.iloc[-1])
                    if dividends is not None and not dividends.empty
                    else None
                ),
                "five_year_growth": info.get("fiveYearAvgDividendYield"),
                "currency": info.get("currency"),
            }
            return result
        except Exception as e:
            return {"ticker": t, "error": str(e)}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _fetch_dividend, ticker.upper())
    return json.dumps(result, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Registry — used by AgentService.initialize()
# ═══════════════════════════════════════════════════════════════════════════

_AGENT_TOOLS = [
    get_portfolio_summary,
    get_portfolio_holdings,
    get_portfolio_performance,
    compare_to_benchmark,
    get_sector_exposure,
    get_portfolio_diversification_score,
    get_market_ohlcv,
    get_market_quote,
    get_ticker_info,
    get_market_news,
    get_lstm_forecast,
    get_spending_analysis,
    get_recent_transactions,
    get_cash_flow_summary,
    compare_tickers_side_by_side,
    get_dividend_insights,
]


def get_all_tools() -> list:
    """Return the full list of agent tool callables for graph registration."""
    return _AGENT_TOOLS
