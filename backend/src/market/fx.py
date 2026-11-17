"""Currency resolution + FX normalisation helpers.

Base currency is GBP (fixed). Market data comes in the instrument's native
currency; we store an ``fx_rate_to_gbp`` (GBP per 1 native unit) alongside
each money value so aggregates stay GBP-correct without per-query FX joins.

Some exchanges quote in minor units: LSE pence (``GBp``), Johannesburg cents
(``ZAc``) and Tel Aviv agorot (``ILA``). Those codes are preserved verbatim
and converted at 1/100 of the major currency, so a 300p quote is £3 — not
£300. Uppercasing ``GBp`` to ``GBP`` would silently collapse that distinction.

* ``resolve_instrument(ticker)`` → (currency, exchange), sourced from the
  ``instruments`` table, lazily populated from yfinance on a miss.
* ``get_fx_rate_to_gbp(currency)`` → :class:`Decimal`, Redis-cached.
* ``current_fx_rates(holdings)`` → ticker → today's rate. Read paths fall
  back to the stored acquisition rate; write paths use the two functions
  above and fail closed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any, Optional

from src.cache.redis import get_redis
from src.database.connection import connection_ctx
from src.market import provider

logger = logging.getLogger(__name__)

_FX_TTL = 3600  # 1 hour — today's rate is "good enough" per plan
_READ_TIMEOUT = 5.0  # seconds — read paths fall back rather than hang on provider retries

# Minor-unit quote codes → (major currency, GBP-per-minor-unit multiplier).
# Codes are case-sensitive: ``GBp`` is pence, ``GBP`` is pounds.
_MINOR_UNITS: dict[str, tuple[str, Decimal]] = {
    "GBp": ("GBP", Decimal("0.01")),
    "GBX": ("GBP", Decimal("0.01")),
    "ZAc": ("ZAR", Decimal("0.01")),
    "ILA": ("ILS", Decimal("0.01")),
}


class InstrumentResolutionError(Exception):
    """The market provider could not resolve an instrument's currency."""


class FxRateUnavailableError(Exception):
    """The market provider could not resolve an FX rate."""


def currency_parts(currency: str | None) -> tuple[str, str, Decimal]:
    """Return ``(canonical_code, major_code, gbp_factor)`` for a quote currency.

    ``gbp_factor`` converts one unit of the quote currency to the major
    currency (``0.01`` for pence/cents/agorot, ``1`` otherwise). Unknown or
    missing codes fall back to GBP at 1.0.
    """
    raw = (currency or "GBP").strip()
    if raw in _MINOR_UNITS:
        major, factor = _MINOR_UNITS[raw]
        return raw, major, factor
    major = raw.upper()
    return major, major, Decimal("1")


async def resolve_instrument(ticker: str) -> tuple[str, Optional[str]]:
    """Return (currency, exchange) for ``ticker``.

    Reads the ``instruments`` table; on a miss, resolves from the market
    provider and persists the row. A provider failure raises
    :class:`InstrumentResolutionError` — defaulting to GBP would record a
    USD/GBp instrument at a 1.0 FX rate and permanently corrupt its GBP value.
    """
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT currency, exchange FROM instruments WHERE ticker = $1", ticker
        )
        if row:
            return row["currency"], row["exchange"]

    try:
        quote = await provider.fetch_quote(ticker)
    except Exception as exc:
        logger.warning("instrument_resolve_failed", extra={"ticker": ticker}, exc_info=True)
        raise InstrumentResolutionError(f"Could not resolve currency for {ticker}") from exc

    raw_currency = quote.get("currency")
    if not raw_currency:
        logger.warning("instrument_resolve_no_currency", extra={"ticker": ticker})
        raise InstrumentResolutionError(f"No currency returned for {ticker}")

    currency, _, _ = currency_parts(raw_currency)
    exchange = quote.get("exchange")

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
        logger.warning("instrument_persist_failed", extra={"ticker": ticker}, exc_info=True)

    return currency, exchange


async def get_fx_rate_to_gbp(currency: str) -> Decimal:
    """Return GBP per 1 unit of ``currency`` (GBP → 1.0), Redis-cached.

    For minor-unit codes the result is GBP per one minor unit: ``GBp`` →
    0.01, ``ZAc`` → the ZAR rate × 0.01. Raises
    :class:`FxRateUnavailableError` when the provider cannot supply a rate.
    """
    _code, major, factor = currency_parts(currency)
    if major == "GBP":
        return factor

    key = f"fx:gbp:{major}"
    try:
        r = await get_redis()
        cached = await r.get(key)
        if cached is not None:
            return Decimal(cached.decode()) * factor
    except Exception:
        logger.warning("fx_cache_read_failed", extra={"currency": currency}, exc_info=True)

    try:
        rate = await provider.fetch_fx(major)
    except Exception as exc:
        logger.warning("fx_rate_fetch_failed", extra={"currency": major}, exc_info=True)
        raise FxRateUnavailableError(f"FX rate unavailable for {major}") from exc

    try:
        r = await get_redis()
        await r.set(key, str(rate), ex=_FX_TTL)
    except Exception:
        logger.warning("fx_cache_write_failed", extra={"currency": currency}, exc_info=True)

    return rate * factor


async def current_fx_rates(holdings: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Return ticker → today's GBP rate for each holding's currency.

    Read-only aggregation helper: a failed lookup falls back to the holding's
    stored ``fx_rate_to_gbp`` (and is logged) rather than making the whole
    portfolio unreadable during a provider outage. Writes must call
    :func:`resolve_instrument` + :func:`get_fx_rate_to_gbp` and fail closed.
    """
    rows = list(holdings)
    if not rows:
        return {}

    codes = {currency_parts(h.get("currency"))[0] for h in rows}

    async def _one(code: str) -> tuple[str, Optional[Decimal]]:
        try:
            return code, await asyncio.wait_for(get_fx_rate_to_gbp(code), _READ_TIMEOUT)
        except Exception:
            logger.warning("fx_rate_fallback_to_stored", extra={"currency": code}, exc_info=True)
            return code, None

    resolved = dict(await asyncio.gather(*(_one(code) for code in codes)))

    rates: dict[str, Decimal] = {}
    for h in rows:
        code = currency_parts(h.get("currency"))[0]
        rate = resolved.get(code)
        if rate is None:
            rate = h.get("fx_rate_to_gbp") or Decimal("1")
        rates[h["ticker"]] = rate
    return rates
