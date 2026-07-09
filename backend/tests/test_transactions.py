"""
Tests for transactions CRUD endpoints.

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx


async def _create_portfolio(client: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.post("/portfolios", json={"name": "Test Portfolio"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()


async def _create_cash_flow(
    client: httpx.AsyncClient,
    pid: str,
    headers: dict[str, str],
    amount: float = 10000.0,
) -> dict:
    """Create a cash flow deposit to fund BUY transactions."""
    payload = {
        "amount": amount,
        "source": "deposit",
        "notes": "Test deposit for transaction tests",
    }
    resp = await client.post(f"/portfolios/{pid}/cash-flows", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


async def _create_transaction(
    client: httpx.AsyncClient,
    pid: str,
    headers: dict[str, str],
    **overrides,
) -> dict:
    payload = {
        "ticker": "AAPL",
        "type": "BUY",
        "shares": "10.0",
        "price_per_share": "150.50",
        "transaction_date": "2026-06-01",
        "notes": "Test purchase",
    }
    payload.update(overrides)
    # Ensure cash is available for BUY transactions
    if payload.get("type") == "BUY":
        shares = float(payload.get("shares", "10.0"))
        price = float(payload.get("price_per_share", "150.50"))
        await _create_cash_flow(client, pid, headers, amount=shares * price * 1.1)
    resp = await client.post(f"/portfolios/{pid}/transactions", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreateTransaction:
    """POST /portfolios/{id}/transactions"""

    async def test_create_buy(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        data = await _create_transaction(
            client,
            p["id"],
            auth_headers,
            ticker="AAPL",
            type="BUY",
            shares="10.0",
            price_per_share="150.50",
            transaction_date="2026-06-01",
        )
        assert data["ticker"] == "AAPL"
        assert data["type"] == "BUY"
        assert float(data["shares"]) == 10.0
        assert float(data["price_per_share"]) == 150.50
        # total_amount = shares * price_per_share
        assert float(data["total_amount"]) == 1505.0
        assert data["portfolio_id"] == p["id"]

    async def test_create_sell(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        response = await client.post(
            f"/portfolios/{p['id']}/transactions",
            json={
                "ticker": "TSLA",
                "type": "SELL",
                "shares": "5.0",
                "price_per_share": "700.0",
                "transaction_date": "2026-06-15",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["type"] == "SELL"
        assert float(response.json()["total_amount"]) == 3500.0

    async def test_create_ticker_uppercased(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        p = await _create_portfolio(client, auth_headers)
        await _create_cash_flow(client, p["id"], auth_headers, amount=200.0)
        response = await client.post(
            f"/portfolios/{p['id']}/transactions",
            json={
                "ticker": "aapl",
                "type": "BUY",
                "shares": "1.0",
                "price_per_share": "100.0",
                "transaction_date": "2026-06-01",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    async def test_create_portfolio_not_found(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        response = await client.post(
            "/portfolios/00000000-0000-0000-0000-000000000000/transactions",
            json={
                "ticker": "AAPL",
                "type": "BUY",
                "shares": "1.0",
                "price_per_share": "100.0",
                "transaction_date": "2026-06-01",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_create_invalid_type(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        p = await _create_portfolio(client, auth_headers)
        response = await client.post(
            f"/portfolios/{p['id']}/transactions",
            json={
                "ticker": "AAPL",
                "type": "HOLD",
                "shares": "1.0",
                "price_per_share": "100.0",
                "transaction_date": "2026-06-01",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_create_future_date(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        p = await _create_portfolio(client, auth_headers)
        future = (date.today() + timedelta(days=2)).isoformat()
        response = await client.post(
            f"/portfolios/{p['id']}/transactions",
            json={
                "ticker": "AAPL",
                "type": "BUY",
                "shares": "1.0",
                "price_per_share": "100.0",
                "transaction_date": future,
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_create_with_notes(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        await _create_cash_flow(client, p["id"], auth_headers, amount=6000.0)
        response = await client.post(
            f"/portfolios/{p['id']}/transactions",
            json={
                "ticker": "GOOGL",
                "type": "BUY",
                "shares": "2.0",
                "price_per_share": "2800.0",
                "transaction_date": "2026-06-10",
                "notes": "Bought the dip",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["notes"] == "Bought the dip"


# ── List ────────────────────────────────────────────────────────────────────


class TestListTransactions:
    """GET /portfolios/{id}/transactions"""

    async def test_list_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        await _create_transaction(client, p["id"], auth_headers, ticker="AAPL")
        await _create_transaction(client, p["id"], auth_headers, ticker="GOOGL")
        response = await client.get(f"/portfolios/{p['id']}/transactions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["transactions"]) == 2

    async def test_list_empty(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        response = await client.get(f"/portfolios/{p['id']}/transactions", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["transactions"] == []

    async def test_list_pagination(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        for i in range(5):
            await _create_transaction(
                client,
                p["id"],
                auth_headers,
                ticker="AAPL",
                notes=f"tx_{i}",
            )
        # limit=2, offset=0
        response = await client.get(
            f"/portfolios/{p['id']}/transactions?limit=2&offset=0",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["transactions"]) == 2
        assert data["total"] == 5

    async def test_list_ticker_filter(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        p = await _create_portfolio(client, auth_headers)
        await _create_transaction(client, p["id"], auth_headers, ticker="AAPL")
        await _create_transaction(client, p["id"], auth_headers, ticker="TSLA")
        response = await client.get(
            f"/portfolios/{p['id']}/transactions?ticker=AAPL",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["transactions"][0]["ticker"] == "AAPL"

    async def test_list_max_limit(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        for i in range(5):
            await _create_transaction(client, p["id"], auth_headers, ticker="AAPL")
        # Requesting limit > 100 should be capped to 100
        response = await client.get(
            f"/portfolios/{p['id']}/transactions?limit=200",
            headers=auth_headers,
        )
        assert response.status_code == 200


# ── Get ─────────────────────────────────────────────────────────────────────


class TestGetTransaction:
    """GET /transactions/{id}"""

    async def test_get_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        txn = await _create_transaction(client, p["id"], auth_headers)
        tid = txn["id"]
        response = await client.get(f"/transactions/{tid}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["id"] == tid

    async def test_get_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get(
            "/transactions/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_nested(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """GET /portfolios/{id}/transactions/{tid} works."""
        p = await _create_portfolio(client, auth_headers)
        txn = await _create_transaction(client, p["id"], auth_headers)
        tid = txn["id"]
        response = await client.get(
            f"/portfolios/{p['id']}/transactions/{tid}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == tid

    async def test_get_nested_wrong_portfolio(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        p1 = await _create_portfolio(client, auth_headers)
        txn = await _create_transaction(client, p1["id"], auth_headers)
        tid = txn["id"]
        # Wrong portfolio ID
        response = await client.get(
            f"/portfolios/{'00000000-0000-0000-0000-000000000000'}/transactions/{tid}",
            headers=auth_headers,
        )
        assert response.status_code == 404
