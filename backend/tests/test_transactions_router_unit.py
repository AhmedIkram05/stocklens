"""DB-free unit tests for the transactions router write-path guards.

The router behaviour suite (test_transactions.py) runs against the test
database in CI; these tests pin the affordability guard and the atomic
holdings upsert locally with stubbed connections.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest


class _StubConn:
    def __init__(self, fetchval_results):
        self._results = list(fetchval_results)
        self.fetchval_queries: list[str] = []

    async def fetchval(self, query, *args):
        self.fetchval_queries.append(query)
        return self._results.pop(0)


async def test_assert_buy_affordable_rejects_when_cost_exceeds_free_cash():
    from fastapi import HTTPException

    from src.transactions.router import _assert_buy_affordable

    conn = _StubConn([Decimal("1000"), Decimal("900")])  # free cash = 100
    with pytest.raises(HTTPException) as exc:
        await _assert_buy_affordable(conn, "p1", Decimal("150"))
    assert exc.value.status_code == 400
    assert "Insufficient funds" in exc.value.detail


async def test_assert_buy_affordable_passes_within_free_cash():
    from src.transactions.router import _assert_buy_affordable

    conn = _StubConn([Decimal("1000"), Decimal("900")])
    await _assert_buy_affordable(conn, "p1", Decimal("100"))  # must not raise
    assert len(conn.fetchval_queries) == 2  # deposits + net invested reads


async def test_apply_buy_to_holdings_is_atomic_upsert():
    from src.transactions.router import _apply_buy_to_holdings

    conn = _StubConn([])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    await _apply_buy_to_holdings(
        conn, "p1", "AAPL", Decimal("10"), Decimal("150"), "USD", Decimal("0.8"), Decimal("120")
    )

    call = conn.execute.call_args
    query = call[0][0]
    # Single statement — no read-modify-write SELECT before it.
    assert "ON CONFLICT (portfolio_id, ticker) DO UPDATE" in query
    assert "SELECT shares, average_cost_basis FROM holdings" not in query
    # Shares add and weighted average read the row's CURRENT values under
    # the conflict row lock (no lost update between concurrent buys).
    assert "holdings.shares + EXCLUDED.shares" in query
    assert "holdings.shares * holdings.average_cost_basis" in query
    # M12: the GBP basis is accumulated per buy from total_amount_gbp
    # (each buy weighted at its own historical FX), not today's rate
    # times the native average.
    assert "holdings.average_cost_basis_gbp," in query
    assert "+ $7::numeric)" in query
    # asyncpg sends params untyped, so `$7 / $3` is `unknown / unknown` to
    # PostgreSQL (AmbiguousFunctionError) — the numeric casts are required.
    assert "$3::numeric" in query
    assert "$7::numeric / $3::numeric" in query
    assert "* EXCLUDED.fx_rate_to_gbp" not in query
    assert "updated_at = now()" in query

    args = call[0][1:]
    assert args[0] == "p1"
    assert args[1] == "AAPL"
    assert args[2] == Decimal("10")
    assert args[3] == Decimal("150")
    # $7 is the buy's GBP amount — the per-buy GBP basis ($7/$3 = £12/share)
    # seeds the insert path.
    assert args[6] == Decimal("120")


async def test_list_transactions_clamps_limit_to_valid_range(monkeypatch):
    """N8: a negative limit reaches Postgres as LIMIT -1 = unlimited; zero
    returns nothing. Both must clamp to the 1..100 range."""
    # src.transactions.__init__ rebinds the name `router` to the APIRouter
    # instance, so `import src.transactions.router as ...` would return that
    # object — import_module always yields the module itself.
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import UUID

    from starlette.requests import Request as StarletteRequest

    router_mod = importlib.import_module("src.transactions.router")

    captured: dict[str, int] = {}
    monkeypatch.setattr(
        router_mod,
        "_fetch_portfolio_from_db",
        AsyncMock(return_value={"user_id": "user-1"}),
    )
    monkeypatch.setattr(router_mod, "_count_transactions_in_portfolio", AsyncMock(return_value=0))

    async def fake_fetch(portfolio_id, limit, offset, ticker=None):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(router_mod, "_fetch_transactions_from_db", fake_fetch)

    # A real Request (not a mock): slowapi's limiter validates its type.
    request = StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    user = SimpleNamespace(id="user-1")
    portfolio_id = UUID(int=1)

    for bad_limit in (-1, -50, 0):
        response = await router_mod.list_transactions(
            request,
            portfolio_id,
            limit=bad_limit,
            offset=0,
            ticker=None,
            current_user=user,
        )
        assert captured["limit"] == 1
        assert response.page_size == 1
        assert response.page == 1

    response = await router_mod.list_transactions(
        request, portfolio_id, limit=500, offset=0, ticker=None, current_user=user
    )
    assert captured["limit"] == 100
    assert response.page_size == 100

    response = await router_mod.list_transactions(
        request, portfolio_id, limit=50, offset=50, ticker=None, current_user=user
    )
    assert captured["limit"] == 50
    assert response.page == 2
