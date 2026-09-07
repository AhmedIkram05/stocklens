"""
GraphQL read facade — Strawberry types + resolvers, plus the ``market_quote``
subscription (60s poller → Redis pub/sub; near-real-time, never "live").

Scalar policy (REST JSON parity): money = float (Decimal coerced),
ids = strawberry.ID, dates/datetimes = ISO-8601, enums = strawberry.enum.
All query resolvers read ``user_id`` from ``info.context["user_id"]``; ownership is
verified once at Portfolio resolution and inherited by child fields.
WS auth is per-subscription via ``connection_params`` (see ``_validate_ws_token``) —
the WS handshake carries an anonymous context (browsers/RN can't set headers).
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import AsyncGenerator
from datetime import date, datetime
from typing import Any
from uuid import UUID

import strawberry
import structlog
from fastapi import HTTPException
from graphql.error import GraphQLError

from src.auth.utils import decode_token
from src.cache.redis import get_redis, is_token_blacklisted
from src.graphql.streaming import (
    _fetch_with_timeout,
    subscribe_symbol,
    unsubscribe_symbol,
)
from src.market import quotes as market_quotes
from src.performance.queries import (
    batch_get_cash_flows,
    batch_get_holdings,
    batch_get_transactions,
    get_benchmark_comparison,
    get_bulk_portfolio_performance,
    get_cash_flows_sorted,
    get_holdings,
    get_portfolio_performance,
    get_transactions_sorted,
)
from src.performance.schemas import (
    BenchmarkComparisonResponse,
    PortfolioPerformanceResponse,
)
from src.portfolios.queries import fetch_portfolio_by_id, fetch_portfolios_from_db

logger = structlog.get_logger(__name__)


def _f(value: Any) -> float | None:
    """Coerce a Decimal/float money value to float (None-safe)."""
    return float(value) if value is not None else None


def _as_date(value: Any) -> date:
    """Coerce a date/datetime/ISO-string column to ``datetime.date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _as_datetime(value: Any) -> datetime | None:
    """Coerce a datetime/ISO-string value (JSON-cached quotes store ISO strings)."""
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


@strawberry.enum
class TransactionType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


@strawberry.type
class Holding:
    id: strawberry.ID
    portfolio_id: strawberry.ID
    ticker: str
    shares: float
    average_cost_basis: float
    currency: str
    fx_rate_to_gbp: float | None
    average_cost_basis_gbp: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Holding:
        return cls(
            id=strawberry.ID(str(row["id"])),
            portfolio_id=strawberry.ID(str(row["portfolio_id"])),
            ticker=row["ticker"],
            shares=float(row["shares"]),
            average_cost_basis=float(row["average_cost_basis"]),
            currency=row["currency"],
            fx_rate_to_gbp=_f(row.get("fx_rate_to_gbp")),
            average_cost_basis_gbp=_f(row.get("average_cost_basis_gbp")),
        )


@strawberry.type
class Transaction:
    id: strawberry.ID
    ticker: str
    type: TransactionType
    shares: float
    price_per_share: float
    total_amount: float
    total_amount_gbp: float | None
    date: date

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Transaction:
        return cls(
            id=strawberry.ID(str(row["id"])),
            ticker=row["ticker"],
            type=TransactionType[row["type"]],
            shares=float(row["shares"]),
            price_per_share=float(row["price_per_share"]),
            total_amount=float(row["total_amount"]),
            total_amount_gbp=_f(row.get("total_amount_gbp")),
            date=_as_date(row["date"]),
        )


@strawberry.type
class CashFlow:
    id: strawberry.ID
    portfolio_id: strawberry.ID
    amount: float
    source: str
    source_id: str | None
    notes: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CashFlow:
        return cls(
            id=strawberry.ID(str(row["id"])),
            portfolio_id=strawberry.ID(str(row["portfolio_id"])),
            amount=float(row["amount"]),
            source=row["source"],
            source_id=row.get("source_id"),
            notes=row.get("notes"),
            created_at=row["created_at"],
        )


@strawberry.type
class Quote:
    ticker: str
    price: float | None
    change: float | None
    change_pct: float | None
    previous_close: float | None
    volume: int | None
    currency: str | None
    exchange: str | None
    timestamp: datetime | None


def _to_quote(q: dict[str, Any]) -> Quote:
    volume = q.get("volume")
    return Quote(
        ticker=q["ticker"],
        price=_f(q.get("price")),
        change=_f(q.get("change")),
        change_pct=_f(q.get("change_pct")),
        previous_close=_f(q.get("previous_close")),
        volume=int(volume) if volume is not None else None,
        currency=q.get("currency"),
        exchange=q.get("exchange"),
        timestamp=_as_datetime(q.get("timestamp")),
    )


@strawberry.type
class HoldingPerformance:
    ticker: str
    shares: float
    average_cost_basis: float
    current_price: float | None
    currency: str
    market_value: float | None
    cost_basis: float
    unrealised_pl: float | None
    unrealised_pl_pct: float | None
    day_change: float | None
    day_change_pct: float | None
    portfolio_weight_pct: float | None


@strawberry.type
class PortfolioPerformance:
    portfolio_id: strawberry.ID
    portfolio_name: str
    total_market_value: float | None
    total_cost_basis: float
    total_unrealised_pl: float | None
    total_unrealised_pl_pct: float | None
    day_change: float | None
    day_change_pct: float | None
    free_cash_balance: float
    twr: float | None
    twr_annualised: float | None
    twr_start_date: date | None
    twr_end_date: date | None
    twr_methodology: str
    holdings: list[HoldingPerformance]
    total_holdings: int
    data_quality: str
    calculated_at: datetime


def _to_portfolio_performance(resp: PortfolioPerformanceResponse) -> PortfolioPerformance:
    return PortfolioPerformance(
        portfolio_id=strawberry.ID(str(resp.portfolio_id)),
        portfolio_name=resp.portfolio_name,
        total_market_value=_f(resp.total_market_value),
        total_cost_basis=float(resp.total_cost_basis),
        total_unrealised_pl=_f(resp.total_unrealised_pl),
        total_unrealised_pl_pct=_f(resp.total_unrealised_pl_pct),
        day_change=_f(resp.day_change),
        day_change_pct=_f(resp.day_change_pct),
        free_cash_balance=float(resp.free_cash_balance),
        twr=_f(resp.twr),
        twr_annualised=_f(resp.twr_annualised),
        twr_start_date=resp.twr_start_date,
        twr_end_date=resp.twr_end_date,
        twr_methodology=resp.twr_methodology,
        holdings=[
            HoldingPerformance(
                ticker=h.ticker,
                shares=float(h.shares),
                average_cost_basis=float(h.average_cost_basis),
                current_price=_f(h.current_price),
                currency=h.currency,
                market_value=_f(h.market_value),
                cost_basis=float(h.cost_basis),
                unrealised_pl=_f(h.unrealised_pl),
                unrealised_pl_pct=_f(h.unrealised_pl_pct),
                day_change=_f(h.day_change),
                day_change_pct=_f(h.day_change_pct),
                portfolio_weight_pct=_f(h.portfolio_weight_pct),
            )
            for h in resp.holdings
        ],
        total_holdings=resp.total_holdings,
        data_quality=resp.data_quality,
        calculated_at=resp.calculated_at,
    )


@strawberry.type
class CumulativeReturn:
    date: date
    value: float


@strawberry.type
class BenchmarkComparison:
    portfolio_id: strawberry.ID
    benchmark_ticker: str
    portfolio_return: float | None
    benchmark_return: float | None
    excess_return_alpha: float | None
    tracking_error: float | None
    information_ratio: float | None
    period_start: date
    period_end: date
    methodology: str
    daily_returns_count: int
    calculated_at: datetime
    portfolio_cumulative_returns: list[CumulativeReturn]
    benchmark_cumulative_returns: list[CumulativeReturn]


def _to_cumulative_returns(series: list[dict[str, Any]]) -> list[CumulativeReturn]:
    return [
        CumulativeReturn(date=_as_date(point["date"]), value=float(point["value"]))
        for point in series
    ]


def _to_benchmark_comparison(resp: BenchmarkComparisonResponse) -> BenchmarkComparison:
    return BenchmarkComparison(
        portfolio_id=strawberry.ID(str(resp.portfolio_id)),
        benchmark_ticker=resp.benchmark_ticker,
        portfolio_return=_f(resp.portfolio_return),
        benchmark_return=_f(resp.benchmark_return),
        excess_return_alpha=_f(resp.excess_return_alpha),
        tracking_error=_f(resp.tracking_error),
        information_ratio=_f(resp.information_ratio),
        period_start=resp.period_start,
        period_end=resp.period_end,
        methodology=resp.methodology,
        daily_returns_count=resp.daily_returns_count,
        calculated_at=resp.calculated_at,
        portfolio_cumulative_returns=_to_cumulative_returns(resp.portfolio_cumulative_returns),
        benchmark_cumulative_returns=_to_cumulative_returns(resp.benchmark_cumulative_returns),
    )


@strawberry.type
class Portfolio:
    id: strawberry.ID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Portfolio:
        return cls(
            id=strawberry.ID(str(row["id"])),
            name=row["name"],
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _cached(self, info: strawberry.Info, key: str) -> Any | None:
        return info.context.get("children", {}).get(str(self.id), {}).get(key)

    @strawberry.field
    async def holdings(self, info: strawberry.Info) -> list[Holding]:
        rows = self._cached(info, "holdings")
        if rows is None:
            rows = await get_holdings(str(self.id))
        return [Holding.from_row(r) for r in rows]

    @strawberry.field
    async def transactions(self, info: strawberry.Info) -> list[Transaction]:
        rows = self._cached(info, "transactions")
        if rows is None:
            rows = await get_transactions_sorted(str(self.id))
        return [Transaction.from_row(r) for r in rows]

    @strawberry.field
    async def cash_flows(self, info: strawberry.Info) -> list[CashFlow]:
        rows = self._cached(info, "cash_flows")
        if rows is None:
            rows = await get_cash_flows_sorted(str(self.id))
        return [CashFlow.from_row(r) for r in rows]

    @strawberry.field
    async def performance(
        self,
        info: strawberry.Info,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> PortfolioPerformance:
        if start_date is None and end_date is None:
            preloaded = self._cached(info, "performance")
            if preloaded is not None:
                return _to_portfolio_performance(preloaded)
        resp = await get_portfolio_performance(
            UUID(str(self.id)), info.context["user_id"], start_date, end_date
        )
        return _to_portfolio_performance(resp)

    @strawberry.field
    async def benchmark(
        self,
        info: strawberry.Info,
        benchmark: str = "SPY",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> BenchmarkComparison:
        try:
            resp = await get_benchmark_comparison(
                UUID(str(self.id)),
                benchmark,
                start_date,
                end_date,
                info.context["user_id"],
            )
        except HTTPException as exc:
            raise GraphQLError(exc.detail)
        return _to_benchmark_comparison(resp)


@strawberry.type
class Query:
    @strawberry.field
    async def portfolios(self, info: strawberry.Info) -> list[Portfolio]:
        user_id = info.context["user_id"]
        rows = await fetch_portfolios_from_db(user_id)
        pids = [str(r["id"]) for r in rows]
        if pids:
            # ONE batched compute — mirrors the REST bulk endpoint exactly.
            bulk = await get_bulk_portfolio_performance(pids, user_id)
            # Preload children cache (dataloader pattern, no extra lib):
            # 3 batched DB reads for N portfolios, not N×.
            holdings_by_pid = await batch_get_holdings(pids)
            txns_by_pid = await batch_get_transactions(pids)
            cfs_by_pid = await batch_get_cash_flows(pids)
            info.context["children"] = {
                pid: {
                    "holdings": holdings_by_pid.get(pid, []),
                    "transactions": txns_by_pid.get(pid, []),
                    "cash_flows": cfs_by_pid.get(pid, []),
                    "performance": bulk.portfolios.get(pid),
                }
                for pid in pids
            }
        return [Portfolio.from_row(r) for r in rows]

    @strawberry.field
    async def portfolio(self, info: strawberry.Info, id: strawberry.ID) -> Portfolio | None:
        # None → null (no existence leak; no HTTP 404 in GraphQL).
        row = await fetch_portfolio_by_id(str(id), info.context["user_id"])
        return Portfolio.from_row(row) if row is not None else None

    @strawberry.field
    async def market_quote(self, info: strawberry.Info, ticker: str) -> Quote:
        del info  # market data is not user-scoped; auth already enforced by context
        ticker = ticker.upper()
        if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker):
            raise GraphQLError(f"Invalid ticker: {ticker!r}")
        try:
            q = await market_quotes.get_quote(ticker)
        except Exception:
            raise GraphQLError(f"Quote temporarily unavailable for {ticker}")
        return _to_quote(q)


async def _validate_ws_token(token: str) -> None:
    """WS auth: same primitives as ``get_current_user`` minus the DB user fetch
    (market data is not user-scoped). Raises ``GraphQLError("Forbidden")`` on
    any failure — expired/missing/blacklisted/non-access token."""
    try:
        payload = decode_token(token)
        blacklisted = await is_token_blacklisted(payload.jti)
    except Exception:
        raise GraphQLError("Forbidden")
    if payload.type != "access" or blacklisted:
        raise GraphQLError("Forbidden")


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def market_quote(self, info: strawberry.Info, ticker: str) -> AsyncGenerator[Quote, None]:
        """Near-real-time quote stream (~15-min-delayed Yahoo data, 60s poll) — never "live"."""
        ticker = ticker.upper()
        if not re.fullmatch(r"[A-Z0-9.]{1,10}", ticker):
            raise GraphQLError(f"Invalid ticker: {ticker!r}")
        # WS auth at connection_init — browser/RN WS can't set headers.
        params = info.context.get("connection_params") or {}
        token = (params.get("authToken") or "").removeprefix("Bearer ").strip()
        await _validate_ws_token(token)

        subscribe_symbol(ticker)
        channel = f"quote:stream:{ticker}"
        pubsub = None
        try:
            redis = await get_redis()
            pubsub = redis.pubsub()
            # Subscribe FIRST — a tick published between the replay read and
            # subscribe would otherwise be missed.
            await pubsub.subscribe(channel)
            # Last-value replay (fetch-if-miss; cache+setex doubles as the replay store).
            yield _to_quote(await _fetch_with_timeout(ticker))
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    yield _to_quote(json.loads(message["data"]))
        finally:
            try:
                if pubsub is not None:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
            except Exception:
                logger.warning("ws_pubsub_close_failed", symbol=ticker)
            unsubscribe_symbol(ticker)


schema = strawberry.Schema(query=Query, subscription=Subscription)

# Re-exported for tests (patch targets live in this namespace).
__all__ = [
    "batch_get_cash_flows",
    "batch_get_holdings",
    "batch_get_transactions",
    "get_benchmark_comparison",
    "get_bulk_portfolio_performance",
    "get_portfolio_performance",
    "schema",
]
