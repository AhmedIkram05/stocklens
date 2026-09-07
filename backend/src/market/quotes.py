"""Cached quote fetch — the single quote-fetch path for REST + performance.

Redis GET ``quote:{TICKER}`` → hit; miss → provider ``fetch_quote`` → SETEX 60s.
Redis failures log + degrade (never block the fetch); provider failures
**propagate** (caller decides: REST 503, perf gather-skips). No stale-cache
fallback — a stale price can mislead; the 60s TTL already bounds yfinance load.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from src.cache.redis import get_redis
from src.market.provider import fetch_quote

logger = structlog.get_logger()

QUOTE_CACHE_TTL = 60  # seconds — glossary normative (was 30 in market/router.py; bug fix)


def _quote_key(ticker: str) -> str:
    return f"quote:{ticker.upper()}"


async def get_quote(ticker: str) -> dict[str, Any]:
    """Return the quote dict for *ticker*, via the 1-min Redis cache."""
    key = _quote_key(ticker)
    try:
        r = await get_redis()
        cached = await r.get(key)
        if cached is not None:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                logger.warning("quote_cache_corrupt", ticker=ticker.upper())
    except Exception:
        logger.warning("quote_cache_read_failed", ticker=ticker.upper(), exc_info=True)
    quote = await fetch_quote(ticker)  # propagates on provider failure
    try:
        r = await get_redis()
        await r.setex(key, QUOTE_CACHE_TTL, json.dumps(quote, default=str))
    except Exception:
        logger.warning("quote_cache_write_failed", ticker=ticker.upper(), exc_info=True)
    return quote
