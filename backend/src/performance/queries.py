"""
Shared read layer for portfolio performance and benchmark comparison.

Database fetch helpers plus the single-portfolio performance and benchmark
builds, shared by the REST router and (Phase 3) the GraphQL resolvers.
No HTTP route handling here — only ``HTTPException`` for domain errors
(not-found / bad-request), exactly as the routes raised before.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import HTTPException, status

from src.config import settings
from src.database.connection import connection_ctx
from src.market.fx import current_fx_rates
from src.market.provider import fetch_ohlcv
from src.market.quotes import get_quote
from src.market.repository import (
    get_earliest_ohlcv_date,
    get_latest_ohlcv_date,
    get_ohlcv_batch,
    upsert_ohlcv,
)
from src.market.router import refresh_ohlcv_if_stale
from src.performance.calculations import (
    _get_closest_price,
    _sorted_price_dates,
    align_daily_return_series,
    compute_benchmark_comparison,
    compute_live_valuation,
    compute_portfolio_performance,
)
from src.performance.schemas import (
    BenchmarkComparisonResponse,
    BulkPerformanceResponse,
    PortfolioPerformanceResponse,
)

logger = structlog.get_logger()


async def verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, user_id, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


async def get_holdings(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch holdings for a portfolio (incl. currency / GBP-normalised cols)."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, ticker, shares, average_cost_basis, "
            "currency, fx_rate_to_gbp, average_cost_basis_gbp "
            "FROM holdings WHERE portfolio_id = $1::uuid "
            "ORDER BY ticker",
            portfolio_id,
        )
    return [dict(r) for r in rows]


async def get_transactions_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all transactions for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, ticker, type, shares, price_per_share, total_amount, "
            "total_amount_gbp, transaction_date "
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


async def get_cash_flows_sorted(portfolio_id: str) -> list[dict[str, Any]]:
    """Fetch all cash flows for a portfolio, sorted by date ascending."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at ASC, id ASC",
            portfolio_id,
        )
    return [dict(r) for r in rows]


async def get_free_cash_balance(portfolio_id: str) -> Decimal:
    """Compute free cash = total deposits - net invested (BUYs - SELLs)."""
    async with connection_ctx() as conn:
        total_deposits = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
        net_invested = await conn.fetchval(
            "SELECT COALESCE(SUM(CASE WHEN type = 'BUY' THEN total_amount_gbp "
            "WHEN type = 'SELL' THEN -total_amount_gbp ELSE 0 END), 0) "
            "FROM transactions WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    return Decimal(str(total_deposits)) - Decimal(str(net_invested))


async def build_price_map(
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


# Cap concurrent coverage fetches so a 20-holding portfolio cannot fan out one
# yfinance download per holding at once. Each miss fetches only the requested
# window, never the provider's 20-year default.
_COVERAGE_CONCURRENCY = 4
_COVERAGE_TIMEOUT = 10.0  # seconds per ticker; provider retries can take minutes
_COVERAGE_TOTAL_TIMEOUT = 10.0  # whole-coverage budget for one request


async def _ensure_ohlcv_window(ticker: str, start_date: date, end_date: date) -> None:
    """Fetch and store *ticker*'s OHLCV only when the requested window is missing.

    ``build_price_map`` reads stored rows only, so a ticker never opened via
    ``/market/ohlcv`` produced an empty series and a silently partial portfolio
    (BE-M32). Check both ends of the window so a shallow cache is backfilled and
    a stale one is refreshed. Provider/DB failures are logged, never fatal: the
    caller still gets whatever prices are already stored.
    """
    try:
        earliest = await get_earliest_ohlcv_date(ticker)
        latest = await get_latest_ohlcv_date(ticker)
        reference_end = min(end_date, datetime.now(timezone.utc).date())
        if (
            earliest is not None
            and latest is not None
            and earliest <= start_date
            # Weekend/holiday tolerance: Friday's close covers a Monday request.
            and latest >= reference_end - timedelta(days=3)
        ):
            return
        rows = await asyncio.wait_for(
            fetch_ohlcv(ticker, start_date=start_date, end_date=end_date),
            timeout=_COVERAGE_TIMEOUT,
        )
        if rows:
            await upsert_ohlcv(ticker, rows)
    except Exception as exc:
        logger.warning("ohlcv_window_fetch_failed", ticker=ticker, error=str(exc), exc_info=True)


async def _ensure_ohlcv_coverage(tickers: list[str], start_date: date, end_date: date) -> None:
    """Ensure every ticker has prices for the requested window, bounded parallel."""
    semaphore = asyncio.Semaphore(_COVERAGE_CONCURRENCY)
    unique = list(dict.fromkeys(tickers))

    async def _one(ticker: str) -> None:
        async with semaphore:
            await _ensure_ohlcv_window(ticker, start_date, end_date)

    try:
        await asyncio.wait_for(
            asyncio.gather(*(_one(ticker) for ticker in unique)),
            timeout=_COVERAGE_TOTAL_TIMEOUT,
        )
    except Exception as exc:
        logger.warning("ohlcv_coverage_incomplete", error=str(exc), exc_info=True)


# Cap concurrent live-quote fetches (each cache-miss offloads to the default
# executor) and bound each fetch so a stalled provider cannot pin worker
# threads and hang the performance endpoint.
_LIVE_QUOTE_CONCURRENCY = 8
_LIVE_QUOTE_TIMEOUT = 10.0  # seconds per quote fetch


async def fetch_live_quotes(
    tickers: list[str],
) -> dict[str, tuple[Decimal, Decimal]]:
    """Fetch live quotes in parallel, returning {ticker: (price, previous_close)}.

    Failures are logged and silently skipped — the caller falls back to OHLCV data.
    """

    semaphore = asyncio.Semaphore(_LIVE_QUOTE_CONCURRENCY)

    async def _get_quote(ticker: str):
        async with semaphore:
            return await asyncio.wait_for(get_quote(ticker), timeout=_LIVE_QUOTE_TIMEOUT)

    results: list[Any] = await asyncio.gather(
        *(_get_quote(t) for t in tickers), return_exceptions=True
    )

    quotes: dict[str, tuple[Decimal, Decimal]] = {}
    for ticker, result in zip(tickers, results):
        if isinstance(result, Exception):
            logger.warning("live_quote_fetch_failed", ticker=ticker, error=str(result))
            continue
        # get_quote may serve a Redis-cached dict where Decimals round-tripped
        # through JSON as strings — coerce back so the Decimal contract holds.
        price = result["price"]
        prev_close = result["previous_close"]
        quotes[ticker] = (
            price if isinstance(price, Decimal) else Decimal(str(price)),
            prev_close if isinstance(prev_close, Decimal) else Decimal(str(prev_close)),
        )
    return quotes


# ── Batch helpers ────────────────────────────────────────────────────────────


async def batch_verify_ownership(portfolio_ids: list[str], user_id: str) -> dict[str, str]:
    """Verify all portfolios belong to *user_id*; return {id: name}."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, name FROM portfolios WHERE id = ANY($1::uuid[]) AND user_id = $2::uuid",
            portfolio_ids,
            user_id,
        )
    return {str(r["id"]): r["name"] for r in rows}


async def batch_get_holdings(
    portfolio_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, ticker, shares, average_cost_basis, "
            "currency, fx_rate_to_gbp, average_cost_basis_gbp "
            "FROM holdings WHERE portfolio_id = ANY($1::uuid[]) "
            "ORDER BY ticker",
            portfolio_ids,
        )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        result[str(r["portfolio_id"])].append(dict(r))
    return result


async def batch_get_transactions(
    portfolio_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, total_amount_gbp, transaction_date "
            "FROM transactions WHERE portfolio_id = ANY($1::uuid[]) "
            "ORDER BY transaction_date ASC, created_at ASC, id ASC",
            portfolio_ids,
        )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        d = dict(r)
        d["date"] = d.pop("transaction_date")
        result[str(d["portfolio_id"])].append(d)
    return result


async def batch_get_cash_flows(
    portfolio_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = ANY($1::uuid[]) "
            "ORDER BY created_at ASC, id ASC",
            portfolio_ids,
        )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        result[str(r["portfolio_id"])].append(dict(r))
    return result


# ── Bulk build (shared by the REST bulk route and the GraphQL list query) ──


async def get_bulk_portfolio_performance(
    portfolio_ids: list[str], user_id: str
) -> BulkPerformanceResponse:
    """Return performance metrics for multiple portfolios in one batched compute.

    Batches all database reads (1 ownership + 3 domain queries) plus one
    price_map and one live-quote fetch across all tickers — not N×.
    Raises 404 when none of *portfolio_ids* belong to *user_id*.
    """
    # 1. Verify ownership + get portfolio names (1 query)
    portfolio_names = await batch_verify_ownership(portfolio_ids, user_id)
    if not portfolio_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No portfolios found for this user",
        )

    # 2. Batch all domain data (3 queries total)
    holdings_by_pid = await batch_get_holdings(portfolio_ids)
    txns_by_pid = await batch_get_transactions(portfolio_ids)
    cfs_by_pid = await batch_get_cash_flows(portfolio_ids)

    # 3. Collect all unique tickers across all portfolios
    all_tickers: set[str] = set()
    for holdings in holdings_by_pid.values():
        all_tickers.update(h["ticker"] for h in holdings)

    # Price data (batched across all tickers)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=365)

    if all_tickers:
        tickers = list(all_tickers)
        await _ensure_ohlcv_coverage(tickers, start_date, end_date)
        price_map = await build_price_map(tickers, start_date, end_date)
        live_quotes = await fetch_live_quotes(tickers)

        # Today's FX rate per ticker (read path; falls back to the stored rate)
        fx_rates = await current_fx_rates(
            [h for holdings in holdings_by_pid.values() for h in holdings]
        )
    else:
        price_map = {}
        live_quotes = {}
        fx_rates = {}

    # 4. Compute per-portfolio performance
    results: dict[str, PortfolioPerformanceResponse] = {}
    for pid in portfolio_ids:
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
                (Decimal(str(t["total_amount_gbp"])) for t in transactions if t["type"] == "BUY"),
                Decimal(0),
            ) - sum(
                (Decimal(str(t["total_amount_gbp"])) for t in transactions if t["type"] == "SELL"),
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


# ── Single-portfolio builds (shared by REST routes and GraphQL resolvers) ────


async def get_portfolio_performance(
    portfolio_id: UUID,
    user_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> PortfolioPerformanceResponse:
    """Return portfolio performance metrics including TWR and per-holding P&L.

    Requires the portfolio to belong to *user_id*.
    Data freshness depends on market data cache (see /market/ohlcv/{ticker}).
    """
    portfolio = await verify_portfolio_ownership(str(portfolio_id), user_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = datetime.now(timezone.utc).date()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    holdings = await get_holdings(str(portfolio_id))
    if not holdings:
        free_cash = await get_free_cash_balance(str(portfolio_id))
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

    transactions = await get_transactions_sorted(str(portfolio_id))
    cash_flows = await get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    # GBP per 1 native unit, per holding, at today's rate. Cost basis comes
    # from the accumulated GBP column, not this rate. No historical FX series
    # exists, so a historical end_date still uses today's rate for FX.
    fx_rates = await current_fx_rates(holdings)

    await _ensure_ohlcv_coverage(tickers, start_date, end_date)
    price_map = await build_price_map(tickers, start_date, end_date)

    # Live intraday quotes only belong to a period that ends today; applying
    # them to a historical end_date would rewrite the past.
    live_quotes = (
        await fetch_live_quotes(tickers) if end_date >= datetime.now(timezone.utc).date() else {}
    )

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
        fx_rates=fx_rates,
    )


async def get_portfolio_valuation(
    portfolio_id: str,
    user_id: str,
    live_quotes: Optional[dict[str, tuple[Decimal, Decimal]]] = None,
) -> PortfolioPerformanceResponse:
    """Live valuation for the ``portfolioValuation`` subscription.

    Requires the portfolio to belong to *user_id*. Reuses ``get_holdings`` and
    the shared valuation math; skips OHLCV/TWR work that a 60s tick cannot
    afford. ``live_quotes`` may be supplied by a caller that already fetched
    them, otherwise they are fetched here (Redis-cached 60s).
    """
    try:
        UUID(portfolio_id)
    except (ValueError, AttributeError):
        # A non-UUID id would otherwise reach asyncpg as a cast error.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    portfolio = await verify_portfolio_ownership(portfolio_id, user_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    # Canonicalise — UUID casing from the client must not fork the registry key.
    canonical_id = str(portfolio["id"])
    holdings = await get_holdings(canonical_id)
    free_cash = await get_free_cash_balance(canonical_id)
    tickers = sorted({h["ticker"] for h in holdings})

    if live_quotes is None:
        live_quotes = await fetch_live_quotes(tickers) if tickers else {}
    fx_rates = await current_fx_rates(holdings) if holdings else {}

    return compute_live_valuation(
        portfolio_id=canonical_id,
        portfolio_name=portfolio["name"],
        holdings_data=holdings,
        live_quotes=live_quotes,
        fx_rates=fx_rates,
        free_cash_balance=free_cash,
    )


def _cumulative_series(dates: list[date], returns: list[Decimal]) -> list[dict[str, Any]]:
    """Link daily returns into a cumulative series keyed by the return's own date.

    ``align_daily_return_series`` returns ``dates[i]`` as the day ``returns[i]``
    was realised, so indexing ``dates[i + 1]`` raised IndexError on the final
    element (BE-D1).
    """
    cum = Decimal(1)
    series: list[dict[str, Any]] = []
    for i, r in enumerate(returns):
        cum *= Decimal(1) + r
        series.append({"date": str(dates[i]), "value": float(cum - 1)})
    return series


async def get_benchmark_comparison(
    portfolio_id: UUID,
    benchmark: str,
    start_date: Optional[date],
    end_date: Optional[date],
    user_id: str,
) -> BenchmarkComparisonResponse:
    """Compare portfolio performance to a benchmark index.

    Returns alpha (excess return), tracking error, and information ratio.
    Requires the portfolio to belong to *user_id*.
    """
    portfolio = await verify_portfolio_ownership(str(portfolio_id), user_id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    if end_date is None:
        end_date = datetime.now(timezone.utc).date()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    benchmark = benchmark.upper()
    if benchmark not in ("SPY", "QQQ"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Benchmark must be SPY or QQQ",
        )

    holdings = await get_holdings(str(portfolio_id))
    transactions = await get_transactions_sorted(str(portfolio_id))
    cash_flows = await get_cash_flows_sorted(str(portfolio_id))
    tickers = list({h["ticker"] for h in holdings})

    fx_rates = await current_fx_rates(holdings)

    all_tickers = list(set(tickers + [benchmark]))

    # Ensure benchmark OHLCV data covers the requested start_date.
    # refresh_ohlcv_if_stale only checks recency (1-3 days), not depth.
    # yfinance defaults to 1 year when start_date=None, so longer periods
    # may need a wider fetch.
    # Bound the provider calls: the shared retry chain can wait minutes. A
    # timeout leaves whatever is already stored for the comparison.
    try:
        await asyncio.wait_for(refresh_ohlcv_if_stale(benchmark), timeout=_COVERAGE_TIMEOUT)
    except TimeoutError:
        logger.warning("benchmark_refresh_timeout", benchmark=benchmark)
    earliest = await get_earliest_ohlcv_date(benchmark)
    logger.info(
        "coverage_check", benchmark=benchmark, earliest=str(earliest), start_date=str(start_date)
    )
    if earliest is None or earliest > start_date:
        try:
            rows = await asyncio.wait_for(
                fetch_ohlcv(benchmark, start_date=start_date, end_date=end_date),
                timeout=_COVERAGE_TIMEOUT,
            )
        except Exception as exc:
            logger.warning(
                "benchmark_coverage_fetch_failed",
                benchmark=benchmark,
                error=str(exc),
                exc_info=True,
            )
            rows = []
        logger.info("coverage_fetch", benchmark=benchmark, rows_fetched=len(rows))
        if rows:
            inserted = await upsert_ohlcv(benchmark, rows)
            logger.info("coverage_upsert", benchmark=benchmark, rows_inserted=inserted)

    await _ensure_ohlcv_coverage(tickers, start_date, end_date)
    price_map = await build_price_map(all_tickers, start_date, end_date, limit=50000)

    if not price_map.get(benchmark):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data found for benchmark {benchmark}",
        )

    # Live quotes only for a period ending today (see get_portfolio_performance)
    live_quotes = (
        await fetch_live_quotes(tickers) if end_date >= datetime.now(timezone.utc).date() else {}
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
        live_quotes=live_quotes,
        fx_rates=fx_rates,
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
    portfolio_dates, portfolio_daily_returns = compute_portfolio_daily_returns(
        holdings=holdings,
        transactions=transactions,
        price_map=price_map,
        start_date=start_date,
        end_date=end_date,
        fx_rates=fx_rates,
    )

    # Join both return series on their common dates: the portfolio calendar
    # (union of all ticker dates) and the benchmark calendar differ whenever
    # either side has a gap, and pairing the lists by position would
    # difference returns from different days.
    common_dates, portfolio_aligned, benchmark_aligned = align_daily_return_series(
        portfolio_dates, portfolio_daily_returns, benchmark_dates, benchmark_daily_returns
    )

    # Build cumulative return series for charting (shared x-axis)
    portfolio_cum = _cumulative_series(common_dates, portfolio_aligned)
    benchmark_cum = _cumulative_series(common_dates, benchmark_aligned)

    comparison = compute_benchmark_comparison(
        portfolio_id=str(portfolio_id),
        portfolio_twr=perf_response.twr,
        benchmark_ticker=benchmark,
        benchmark_daily_returns=benchmark_aligned,
        portfolio_daily_returns=portfolio_aligned,
        period_start=start_date,
        period_end=end_date,
    )
    comparison.portfolio_cumulative_returns = portfolio_cum
    comparison.benchmark_cumulative_returns = benchmark_cum
    return comparison


def compute_portfolio_daily_returns(
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    price_map: dict[str, dict[date, Decimal]],
    start_date: date,
    end_date: date,
    fx_rates: Optional[dict[str, Decimal]] = None,
    live_quotes: Optional[dict[str, tuple[Decimal, Decimal]]] = None,
) -> tuple[list[date], list[Decimal]]:
    """Compute daily portfolio returns for tracking error calculation.

    Reconstructs holdings at each trading day and computes day-over-day
    percentage return. Returns (trading_days, daily_returns). ``live_quotes``
    (ticker -> (price, previous_close)) overrides the stored close on the final
    trading day, matching ``compute_portfolio_performance``.
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

    last_day = trading_days[-1]
    sorted_price_dates = _sorted_price_dates(price_map)
    current: dict[str, Decimal] = {}

    def _apply(txn: dict) -> None:
        ticker = txn["ticker"]
        if txn["type"] == "BUY":
            current[ticker] = current.get(ticker, Decimal(0)) + txn["shares"]
        else:
            current[ticker] = current.get(ticker, Decimal(0)) - txn["shares"]
            if current[ticker] <= 0:
                del current[ticker]

    # Seed positions opened before the window. Without this a buy-and-hold
    # portfolio has no holdings on any day and reports an all-zero series
    # (BE-D9). Trades on the first trading day stay in the loop as flows.
    for txn in transactions:
        if txn["date"] < trading_days[0]:
            _apply(txn)

    def _price_at(ticker: str, day_: date) -> Optional[Decimal]:
        if live_quotes and day_ == last_day:
            quote = live_quotes.get(ticker)
            if quote is not None:
                return quote[0]
        # Closest prior price: a ticker-specific holiday must not value the
        # holding at zero and manufacture a fake -x%/+x% pair (BE-D10).
        return _get_closest_price(price_map, ticker, day_, sorted_price_dates)

    def _value_at(day_: date) -> Decimal:
        """Market value of the current holdings at ``day_``'s prices (GBP)."""
        total = Decimal(0)
        for ticker, shares in current.items():
            price = _price_at(ticker, day_)
            if price is not None:
                fx = (fx_rates or {}).get(ticker, Decimal(1))
                total += shares * price * fx
        return total

    daily_returns: list[Decimal] = []
    previous_value = Decimal(0)

    for i, day in enumerate(trading_days):
        # Value the pre-trade position at today's prices: the day's return is
        # price movement on what was held entering the day. Trades are flows,
        # not P&L — applying them first booked every BUY as a gain and every
        # SELL as a loss, spiking every trade day.
        value = _value_at(day)

        if i > 0:
            prev = previous_value
            if prev > 0:
                daily_return = (value - prev) / prev
                daily_returns.append(daily_return)
            else:
                daily_returns.append(Decimal(0))

        # Apply the day's transactions for the next day's position; the
        # post-trade valuation becomes the next day's base, so a trade's cash
        # value cancels out of the return series.
        for txn in txns_by_date.get(day, []):
            _apply(txn)

        previous_value = _value_at(day)

    return trading_days, daily_returns
