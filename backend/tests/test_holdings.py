"""
Tests for holdings CRUD endpoints.

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

import httpx
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _create_portfolio(client: httpx.AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.post("/portfolios", json={"name": "Test Portfolio"}, headers=headers)
    assert resp.status_code == 201
    return resp.json()


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreateHolding:
    """POST /portfolios/{id}/holdings"""

    async def test_create_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        response = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AAPL", "shares": "10.0", "average_cost_basis": "150.50"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["ticker"] == "AAPL"
        assert float(data["shares"]) == 10.0
        assert float(data["average_cost_basis"]) == 150.50
        assert data["portfolio_id"] == p["id"]

    async def test_create_ticker_uppercased(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Ticker is automatically uppercased."""
        p = await _create_portfolio(client, auth_headers)
        response = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "aapl", "shares": "5.0", "average_cost_basis": "100.0"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["ticker"] == "AAPL"

    async def test_create_portfolio_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Adding a holding to a non-existent portfolio returns 404."""
        response = await client.post(
            "/portfolios/00000000-0000-0000-0000-000000000000/holdings",
            json={"ticker": "AAPL", "shares": "1.0", "average_cost_basis": "100.0"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_create_duplicate_ticker(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Adding the same ticker twice returns an error."""
        p = await _create_portfolio(client, auth_headers)
        await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AAPL", "shares": "10.0", "average_cost_basis": "150.0"},
            headers=auth_headers,
        )
        response = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AAPL", "shares": "5.0", "average_cost_basis": "200.0"},
            headers=auth_headers,
        )
        assert response.status_code == 409  # unique constraint

    async def test_create_other_user_portfolio(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Adding a holding to another user's portfolio returns 404."""
        p = await _create_portfolio(client, auth_headers)
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AAPL", "shares": "1.0", "average_cost_basis": "100.0"},
            headers=other_headers,
        )
        assert response.status_code == 404


# ── List ────────────────────────────────────────────────────────────────────


class TestListHoldings:
    """GET /portfolios/{id}/holdings"""

    async def test_list_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AAPL", "shares": "10.0", "average_cost_basis": "150.0"},
            headers=auth_headers,
        )
        await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "GOOGL", "shares": "5.0", "average_cost_basis": "2800.0"},
            headers=auth_headers,
        )
        response = await client.get(f"/portfolios/{p['id']}/holdings", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        tickers = {h["ticker"] for h in data["holdings"]}
        assert tickers == {"AAPL", "GOOGL"}

    async def test_list_empty(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        response = await client.get(f"/portfolios/{p['id']}/holdings", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == {"holdings": [], "total": 0}


# ── Get ─────────────────────────────────────────────────────────────────────


class TestGetHolding:
    """GET /holdings/{id}"""

    async def test_get_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "MSFT", "shares": "3.0", "average_cost_basis": "330.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.get(f"/holdings/{hid}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["ticker"] == "MSFT"

    async def test_get_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get(
            "/holdings/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_nested_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """GET /portfolios/{id}/holdings/{hid} works."""
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "TSLA", "shares": "2.0", "average_cost_basis": "700.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.get(
            f"/portfolios/{p['id']}/holdings/{hid}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["ticker"] == "TSLA"

    async def test_get_nested_wrong_portfolio(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Nested get with wrong portfolio ID returns 404."""
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "NVDA", "shares": "1.0", "average_cost_basis": "900.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.get(
            f"/portfolios/00000000-0000-0000-0000-000000000000/holdings/{hid}",
            headers=auth_headers,
        )
        assert response.status_code == 404


# ── Update ──────────────────────────────────────────────────────────────────


class TestUpdateHolding:
    """PUT /holdings/{id}"""

    async def test_update_shares(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AMZN", "shares": "1.0", "average_cost_basis": "3000.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.put(
            f"/holdings/{hid}",
            json={"shares": "5.0"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert float(response.json()["shares"]) == 5.0
        # average_cost_basis unchanged
        assert float(response.json()["average_cost_basis"]) == 3000.0

    async def test_update_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.put(
            "/holdings/00000000-0000-0000-0000-000000000000",
            json={"shares": "1.0"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_nested(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """PUT /portfolios/{id}/holdings/{hid} works."""
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "META", "shares": "1.0", "average_cost_basis": "500.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.put(
            f"/portfolios/{p['id']}/holdings/{hid}",
            json={"average_cost_basis": "550.0"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert float(response.json()["average_cost_basis"]) == 550.0

    async def test_update_no_fields(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "NFLX", "shares": "2.0", "average_cost_basis": "600.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.put(
            f"/holdings/{hid}",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 400


# ── Delete ──────────────────────────────────────────────────────────────────


class TestDeleteHolding:
    """DELETE /holdings/{id}"""

    async def test_delete_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "INTC", "shares": "20.0", "average_cost_basis": "50.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.delete(f"/holdings/{hid}", headers=auth_headers)
        assert response.status_code == 204

    async def test_delete_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.delete(
            "/holdings/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_delete_nested(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """DELETE /portfolios/{id}/holdings/{hid} works."""
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "AMD", "shares": "15.0", "average_cost_basis": "120.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        response = await client.delete(
            f"/portfolios/{p['id']}/holdings/{hid}",
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_delete_other_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        p = await _create_portfolio(client, auth_headers)
        created = await client.post(
            f"/portfolios/{p['id']}/holdings",
            json={"ticker": "DIS", "shares": "5.0", "average_cost_basis": "100.0"},
            headers=auth_headers,
        )
        hid = created.json()["id"]
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other2@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.delete(f"/holdings/{hid}", headers=other_headers)
        assert response.status_code == 404
