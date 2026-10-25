"""
Direct tests for the performance read layer (``src.performance.queries``).

Moved helpers (batch getters, price map, daily returns, …) are covered by
the updated ``test_performance.py``; these tests pin the NEW wrapper
functions: ownership enforcement on ``get_portfolio_performance`` /
``get_benchmark_comparison`` and the empty-portfolio branch. All paths
chosen here touch no market/network calls.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from src.performance import queries

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
PID_1 = UUID("11111111-1111-1111-1111-111111111111")


class TestVerifyPortfolioOwnership:
    async def test_owned_returns_row(self):
        """Owned portfolio resolves to its row."""
        row = await queries.verify_portfolio_ownership(str(PID_1), USER_ID)
        assert row is not None
        assert row["name"] == "Test Portfolio"

    async def test_other_user_returns_none(self):
        """Another user's portfolio yields None."""
        assert await queries.verify_portfolio_ownership(str(PID_1), OTHER_USER_ID) is None

    async def test_missing_returns_none(self):
        """Unknown id yields None."""
        assert (
            await queries.verify_portfolio_ownership(
                "00000000-0000-0000-0000-000000000099", USER_ID
            )
            is None
        )


class TestGetPortfolioPerformance:
    async def test_404_for_other_users_portfolio(self):
        """Ownership guard fires before any market/data reads."""
        with pytest.raises(HTTPException, match="Portfolio not found"):
            await queries.get_portfolio_performance(PID_1, OTHER_USER_ID)

    async def test_empty_portfolio_returns_zero_shape(self):
        """Seeded portfolio has no holdings → zero shape, free cash only."""
        response = await queries.get_portfolio_performance(PID_1, USER_ID)
        assert response.portfolio_id == str(PID_1)
        assert response.portfolio_name == "Test Portfolio"
        assert response.total_holdings == 0
        assert response.holdings == []
        assert response.twr is None


class TestGetBenchmarkComparison:
    async def test_404_for_other_users_portfolio(self):
        """Ownership guard fires before any market/data reads."""
        with pytest.raises(HTTPException, match="Portfolio not found"):
            await queries.get_benchmark_comparison(PID_1, "SPY", None, None, OTHER_USER_ID)

    async def test_400_for_invalid_benchmark(self):
        """Ticker validation fires before any network refresh."""
        with pytest.raises(HTTPException, match="Benchmark must be SPY or QQQ"):
            await queries.get_benchmark_comparison(PID_1, "XXX", None, None, USER_ID)


class TestFetchLiveQuotes:
    """M10 regression: bounded concurrency + per-quote timeout."""

    async def test_concurrency_capped(self, monkeypatch):
        import asyncio

        active = 0
        peak = 0

        async def fake_get_quote(ticker: str):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"price": 1, "previous_close": 1}

        monkeypatch.setattr(queries, "get_quote", fake_get_quote)
        quotes = await queries.fetch_live_quotes([f"T{i}" for i in range(20)])
        assert len(quotes) == 20
        assert peak <= queries._LIVE_QUOTE_CONCURRENCY

    async def test_timeout_skips_slow_quote(self, monkeypatch):
        import asyncio

        async def slow_quote(ticker: str):
            await asyncio.sleep(5)

        monkeypatch.setattr(queries, "get_quote", slow_quote)
        monkeypatch.setattr(queries, "_LIVE_QUOTE_TIMEOUT", 0.05)
        quotes = await queries.fetch_live_quotes(["SLOW"])
        assert quotes == {}
