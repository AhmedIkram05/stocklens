"""
Async wrapper around the synchronous yfinance library.

All blocking calls are delegated to ``loop.run_in_executor()`` so the event loop
is never blocked. Data is returned as plain dicts for downstream repository
or response processing.

See ADR 001 for rationale on the sync-wrapping approach.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import yfinance as yf
from requests.exceptions import HTTPError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# ── yfinance 1.x compatibility ─────────────────────────────────────────────
# yfinance >=1.0 uses curl_cffi with built-in TLS impersonation (`query2`
# base URL, modern TLS fingerprint) — no module-level patching needed.
# The retry decorator below handles transient HTTP errors (including 429).


def _is_retryable(exc: BaseException) -> bool:
    """Return True for errors that deserve a retry (incl. 429 rate-limit)."""
    if isinstance(exc, (ConnectionError, TimeoutError, ValueError)):
        return True
    if isinstance(exc, HTTPError):
        return True
    return False


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _download_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Synchronous OHLCV download from yfinance.

    Returns a list of dicts with keys: date, open, high, low, close,
    adjusted_close, volume. NaN values are converted to None.
    """
    # yfinance expects "YYYY-MM-DD" strings
    start_str = start_date.isoformat() if start_date else None
    end_str = end_date.isoformat() if end_date else None

    df = yf.download(ticker, start=start_str, end=end_str, progress=False, auto_adjust=False)

    if df.empty:
        return []

    # yfinance >=1.0 returns MultiIndex columns even for single tickers
    first_col = next(iter(df.columns), None)
    if isinstance(first_col, tuple):
        df.columns = [c[0] for c in df.columns]

    rows = []
    for idx, row in df.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        rows.append(
            {
                "date": d,
                "open": _maybe_decimal(row.get("Open")),
                "high": _maybe_decimal(row.get("High")),
                "low": _maybe_decimal(row.get("Low")),
                "close": _maybe_decimal(row.get("Close")),
                "adjusted_close": _maybe_decimal(row.get("Adj Close")),
                "volume": _maybe_int(row.get("Volume")),
            }
        )
    return rows


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _fetch_quote(ticker: str) -> dict[str, Any]:
    """Synchronous quote fetch from yfinance Ticker.info.

    Returns a dict with keys: price, change, change_pct, previous_close,
    volume, timestamp.
    """
    t = yf.Ticker(ticker)
    info = t.info or {}

    # yfinance.info has various price fields depending on market hours:
    # - regularMarketPrice: current trading price
    # - currentPrice: fallback
    # - previousClose: yesterday's close
    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
    prev_close = info.get("previousClose") or 0
    change = info.get("regularMarketChange") or (price - prev_close)
    change_pct = info.get("regularMarketChangePercent") or (
        (change / prev_close * 100) if prev_close else 0
    )
    volume = info.get("regularMarketVolume") or info.get("volume") or 0

    return {
        "ticker": ticker,
        "price": _maybe_decimal(price),
        "change": _maybe_decimal(change),
        "change_pct": _maybe_decimal(change_pct),
        "previous_close": _maybe_decimal(prev_close),
        "volume": _maybe_int(volume),
        "timestamp": datetime.now(timezone.utc),
    }


def _maybe_decimal(value: Any) -> Optional[Decimal]:
    """Convert a float/None to Decimal or None. Handles NaN."""
    if value is None:
        return None
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return Decimal(str(v))
    except ValueError, TypeError:
        return None


def _maybe_int(value: Any) -> Optional[int]:
    """Convert a float/None to int or None. Handles NaN."""
    if value is None:
        return None
    try:
        v = float(value)
        if v != v:  # NaN check
            return None
        return int(v)
    except ValueError, TypeError:
        return None


# ── Async public API ──


async def fetch_ohlcv(
    ticker: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Fetch OHLCV data from yfinance in a thread pool.

    Defaults to the last 20 years if no dates provided (covers max period picker).
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=20 * 365)
    if end_date is None:
        end_date = date.today()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _download_ohlcv,
        ticker,
        start_date,
        end_date,
    )


async def fetch_quote(ticker: str) -> dict[str, Any]:
    """Fetch current quote from yfinance in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_quote, ticker)
