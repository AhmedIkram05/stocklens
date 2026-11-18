"""60s quote poller → Redis pub/sub fan-out for the GraphQL subscriptions.

Channels are scoped so one user's stream can never carry another user's data:
``quote:stream:{symbol}`` for public market quotes and
``portfolio:stream:{portfolio_id}:{user_id}`` for user-owned portfolios.
"""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import HTTPException

from src.cache.redis import get_redis
from src.market.quotes import get_quote
from src.performance.queries import get_portfolio_valuation

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 60
POLL_FETCH_TIMEOUT_SECONDS = 10
PORTFOLIO_POLL_CONCURRENCY = 10

# Sentinel published when a portfolio subscription must terminate (ownership
# lost). The resolver raises instead of sitting on a dead stream.
PORTFOLIO_STREAM_ERROR = "__error__"

# ponytail: in-process refcount registry; multi-replica would need a Redis-backed registry
_symbol_subscribers: dict[str, int] = {}
_portfolio_subscribers: dict[tuple[str, str], int] = {}
_poller_task: asyncio.Task | None = None


def subscribe_symbol(symbol: str) -> None:
    _symbol_subscribers[symbol] = _symbol_subscribers.get(symbol, 0) + 1


def unsubscribe_symbol(symbol: str) -> None:
    n = _symbol_subscribers.get(symbol, 0) - 1
    if n <= 0:
        _symbol_subscribers.pop(symbol, None)
    else:
        _symbol_subscribers[symbol] = n


def subscribe_portfolio(portfolio_id: str, user_id: str) -> None:
    """Track a subscribed (portfolio, user) pair — identity is part of the key."""
    key = (portfolio_id, user_id)
    _portfolio_subscribers[key] = _portfolio_subscribers.get(key, 0) + 1


def unsubscribe_portfolio(portfolio_id: str, user_id: str) -> None:
    key = (portfolio_id, user_id)
    n = _portfolio_subscribers.get(key, 0) - 1
    if n <= 0:
        _portfolio_subscribers.pop(key, None)
    else:
        _portfolio_subscribers[key] = n


def portfolio_channel(portfolio_id: str, user_id: str) -> str:
    return f"portfolio:stream:{portfolio_id}:{user_id}"


async def _fetch_with_timeout(symbol: str) -> dict:
    """Per-symbol cap — provider retries can stall minutes; cadence must survive."""
    async with asyncio.timeout(POLL_FETCH_TIMEOUT_SECONDS):
        return await get_quote(symbol)


async def _safe_publish(redis, channel: str, payload: str) -> bool:
    """Publish without aborting the tick; returns whether it landed."""
    try:
        await redis.publish(channel, payload)
        return True
    except Exception as exc:
        logger.warning("pubsub_publish_failed", channel=channel, error=str(exc))
        return False


async def _publish_portfolio(
    redis, portfolio_id: str, user_id: str, semaphore: asyncio.Semaphore
) -> None:
    channel = portfolio_channel(portfolio_id, user_id)
    async with semaphore:
        try:
            # Ownership is re-checked inside get_portfolio_valuation.
            async with asyncio.timeout(POLL_FETCH_TIMEOUT_SECONDS):
                valuation = await get_portfolio_valuation(portfolio_id, user_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                logger.warning(
                    "portfolio_valuation_http_error",
                    portfolio_id=portfolio_id,
                    status=exc.status_code,
                )
                return
            # Ownership lost (transferred/deleted): terminate the stream. Only
            # drop the subscription once the sentinel actually reached Redis,
            # otherwise the next tick retries.
            published = await _safe_publish(
                redis, channel, json.dumps({PORTFOLIO_STREAM_ERROR: "Portfolio not found"})
            )
            if published:
                _portfolio_subscribers.pop((portfolio_id, user_id), None)
            return
        except Exception as exc:
            logger.warning(
                "portfolio_valuation_failed",
                portfolio_id=portfolio_id,
                error=str(exc),
                exc_info=True,
            )
            return

    if valuation.data_quality != "complete":
        # Partial pricing would publish an understated total over a good one.
        logger.warning(
            "portfolio_valuation_incomplete",
            portfolio_id=portfolio_id,
            data_quality=valuation.data_quality,
        )
        return

    await _safe_publish(redis, channel, json.dumps(valuation.model_dump(mode="json")))


async def _poller_tick() -> None:
    """One publish round for all subscribed symbols and portfolios. Tests call this."""
    symbols = list(_symbol_subscribers)
    portfolios = list(_portfolio_subscribers)
    if not symbols and not portfolios:
        return

    redis = await get_redis()
    if symbols:
        quotes = await asyncio.gather(
            *[_fetch_with_timeout(s) for s in symbols], return_exceptions=True
        )
        for symbol, quote in zip(symbols, quotes):
            if isinstance(quote, Exception):
                logger.warning("quote_poll_failed", symbol=symbol, error=str(quote))
                continue
            # ponytail: at-most-once per tick, no per-client backpressure at this
            # scale; per-client queues if client count grows
            await _safe_publish(redis, f"quote:stream:{symbol}", json.dumps(quote, default=str))

    if portfolios:
        semaphore = asyncio.Semaphore(PORTFOLIO_POLL_CONCURRENCY)
        await asyncio.gather(
            *(
                _publish_portfolio(redis, portfolio_id, user_id, semaphore)
                for portfolio_id, user_id in portfolios
            )
        )


async def _poller_loop() -> None:
    while True:
        try:
            await _poller_tick()
        except Exception:
            logger.exception("quote_poller_tick_failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def start_quote_poller() -> None:
    """Idempotent start — safe to call from lifespan even if already running."""
    global _poller_task
    if _poller_task is None:
        _poller_task = asyncio.create_task(_poller_loop())


async def stop_quote_poller() -> None:
    global _poller_task
    if _poller_task is not None:
        _poller_task.cancel()
        await asyncio.gather(_poller_task, return_exceptions=True)
        _poller_task = None
