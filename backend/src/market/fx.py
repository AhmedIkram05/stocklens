"""Currency resolution + FX normalisation helpers.

Base currency is GBP (fixed). Market data comes in the instrument's native
currency; we store an ``fx_rate_to_gbp`` (GBP per 1 native unit) alongside
each money value so aggregates stay GBP-correct without per-query FX joins.

* ``resolve_instrument(ticker)`` → (currency, exchange), sourced from the
  ``instruments`` table, lazily populated from yfinance on a miss.
* ``get_fx_rate_to_gbp(currency)`` → :class:`Decimal`, Redis-cached.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from src.cache.redis import get_redis
from src.database.connection import connection_ctx
from src.market import provider

logger = logging.getLogger(__name__)

_FX_TTL = 3600  # 1 hour — today's rate is "good enough" per plan


async def resolve_instrument(ticker: str) -> tuple[str, Optional[str]]:
    """Return (currency, exchange) for ``ticker``.

    Reads the ``instruments`` table; on a miss, resolves from the market
    provider and persists the row. Falls back to GBP on any failure.
    """
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT currency, exchange FROM instruments WHERE ticker = $1", ticker
        )
        if row:
            return row["currency"], row["exchange"]

    try:
        quote = await provider.fetch_quote(ticker)
        currency = (quote.get("currency") or "GBP").upper()
        exchange = quote.get("exchange")
    except Exception:
        logger.warning("instrument_resolve_failed", ticker=ticker, exc_info=True)
        currency, exchange = "GBP", None

    try:
        async with connection_ctx() as conn:
            await conn.execute(
                "INSERT INTO instruments (ticker, currency, exchange) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (ticker) DO UPDATE SET "
                "currency = EXCLUDED.currency, exchange = EXCLUDED.exchange",
                ticker,
                currency,
                exchange,
            )
    except Exception:
        logger.warning("instrument_persist_failed", ticker=ticker, exc_info=True)

    return currency, exchange


async def get_fx_rate_to_gbp(currency: str) -> Decimal:
    """Return GBP per 1 unit of ``currency`` (GBP → 1.0), Redis-cached."""
    if not currency or currency.upper() == "GBP":
        return Decimal("1.0")

    key = f"fx:gbp:{currency.upper()}"
    try:
        r = await get_redis()
        cached = await r.get(key)
        if cached is not None:
            return Decimal(cached.decode())
    except Exception:
        logger.warning("fx_cache_read_failed", currency=currency, exc_info=True)

    rate = await provider.fetch_fx(currency.upper())

    try:
        r = await get_redis()
        await r.set(key, str(rate), ex=_FX_TTL)
    except Exception:
        logger.warning("fx_cache_write_failed", currency=currency, exc_info=True)

    return rate
