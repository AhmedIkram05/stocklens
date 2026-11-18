"""60s quote poller → Redis pub/sub fan-out for the ``market_quote`` subscription."""

from __future__ import annotations

import asyncio
import json

import structlog

from src.cache.redis import get_redis
from src.market.quotes import get_quote
from src.performance.queries import get_portfolio_valuation

logger = structlog.get_logger(__name__)

POLL_INTERVAL_SECONDS = 60
POLL_FETCH_TIMEOUT_SECONDS = 10

# ponytail: in-process refcount registry; multi-replica would need a Redis-backed registry
_symbol_subscribers: dict[str, int] = {}
_portfolio_subscribers: dict[str, tuple[str, int]] = {}
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
    """Track a subscribed portfolio and the user whose quotes it is priced for."""
    owner, count = _portfolio_subscribers.get(portfolio_id, (user_id, 0))
    _portfolio_subscribers[portfolio_id] = (owner, count + 1)


def unsubscribe_portfolio(portfolio_id: str) -> None:
    entry = _portfolio_subscribers.get(portfolio_id)
    if entry is None:
        return
    owner, count = entry
    if count <= 1:
        _portfolio_subscribers.pop(portfolio_id, None)
    else:
        _portfolio_subscribers[portfolio_id] = (owner, count - 1)


async def _fetch_with_timeout(symbol: str) -> dict:
    """Per-symbol cap — provider retries can stall minutes; cadence must survive."""
    async with asyncio.timeout(POLL_FETCH_TIMEOUT_SECONDS):
        return await get_quote(symbol)


async def _poller_tick() -> None:
    """One publish round for all subscribed symbols and portfolios. Tests call this."""
    symbols = list(_symbol_subscribers)
    portfolios = list(_portfolio_subscribers.items())
    if not symbols and not portfolios:
        return

    r = await get_redis()
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
            await r.publish(f"quote:stream:{symbol}", json.dumps(quote, default=str))

    for portfolio_id, (user_id, _count) in portfolios:
        try:
            # Ownership is re-checked inside get_portfolio_valuation — a
            # transferred/deleted portfolio stops streaming on the next tick.
            async with asyncio.timeout(POLL_FETCH_TIMEOUT_SECONDS):
                valuation = await get_portfolio_valuation(portfolio_id, user_id)
        except Exception:
            logger.warning("portfolio_valuation_failed", portfolio_id=portfolio_id)
            continue
        await r.publish(
            f"portfolio:stream:{portfolio_id}",
            json.dumps(valuation.model_dump(mode="json")),
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
