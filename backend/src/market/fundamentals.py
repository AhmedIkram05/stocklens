"""Cached yfinance fundamentals — sector lookups are slow and rarely change."""

from __future__ import annotations

import asyncio
from functools import lru_cache

import yfinance as yf


@lru_cache(maxsize=2048)
def _sector_sync(ticker: str) -> str:
    info = yf.Ticker(ticker).info or {}
    return info.get("sector") or "Unknown"


async def get_sector(ticker: str) -> str:
    """Return the sector for *ticker*, cached for the process lifetime."""
    return await asyncio.to_thread(_sector_sync, ticker.upper())
