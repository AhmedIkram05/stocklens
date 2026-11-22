"""OHLCV refresh locking — concurrent cold requests fetch once."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.market import router as market_router


@pytest.mark.asyncio
async def test_concurrent_refresh_fetches_once(monkeypatch):
    state = {"latest": None, "fetches": 0}

    async def latest(_ticker):
        return state["latest"]

    async def fetch(_ticker, start_date=None, end_date=None):
        state["fetches"] += 1
        await asyncio.sleep(0.05)
        return [{"date": date.today()}]

    async def upsert(_ticker, _rows):
        state["latest"] = date.today()
        return 1

    monkeypatch.setattr(market_router, "get_latest_ohlcv_date", latest)
    monkeypatch.setattr(market_router, "fetch_ohlcv", fetch)
    monkeypatch.setattr(market_router, "upsert_ohlcv", upsert)

    results = await asyncio.gather(
        market_router.refresh_ohlcv_if_stale("AAPL"),
        market_router.refresh_ohlcv_if_stale("AAPL"),
    )
    assert results == [True, False]
    assert state["fetches"] == 1
