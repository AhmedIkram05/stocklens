"""
Tests for the cash flows module.

Covers repository CRUD (real DB) and router endpoints (authenticated).
"""

from __future__ import annotations

from decimal import Decimal

# ──────────────────────────────────────────────────────────────────────
# Repository — create / list / get / update / sum / count
# ──────────────────────────────────────────────────────────────────────


class TestCashFlowRepository:
    """Direct repository tests (DB-backed, inside transaction rollback)."""

    async def _create_portfolio(self, user_id: str) -> str:
        """Helper: create a test portfolio and return its ID."""
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            row = await conn.fetchrow(
                "INSERT INTO portfolios (name, user_id) VALUES ($1, $2::uuid) RETURNING id",
                "Test Portfolio",
                user_id,
            )
        return str(row["id"])

    async def test_create_cash_flow(self, auth_headers, client):
        """Create a cash flow via repository and verify the row exists."""
        from src.cash_flows.repository import (
            count_cash_flows,
            create_cash_flow,
            get_cash_flow,
            list_cash_flows,
            sum_cash_flows,
        )

        # Get user ID by looking up the registered user
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", "test@stocklens.dev"
            )
        assert user_row is not None, "Test user must exist (auth_headers fixture)"
        user_id = str(user_row["id"])

        portfolio_id = await self._create_portfolio(user_id)

        result = await create_cash_flow(
            portfolio_id=portfolio_id,
            amount=Decimal("500.00"),
            source="manual",
            notes="Test deposit",
        )
        assert result["id"] is not None
        assert str(result["portfolio_id"]) == portfolio_id
        assert result["amount"] == Decimal("500.00")
        assert result["source"] == "manual"
        assert result["notes"] == "Test deposit"

        # Verify via get_cash_flow
        fetched = await get_cash_flow(result["id"])
        assert fetched is not None
        assert fetched["amount"] == Decimal("500.00")

        # Verify list contains it
        rows = await list_cash_flows(portfolio_id)
        assert len(rows) == 1

        # Verify count
        count = await count_cash_flows(portfolio_id)
        assert count == 1

        # Verify sum
        total = await sum_cash_flows(portfolio_id)
        assert total == Decimal("500.00")

    async def test_create_cash_flow_with_source_id(self, auth_headers, client):
        """Create a cash flow linked to a receipt source_id."""
        from src.cash_flows.repository import create_cash_flow
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", "test@stocklens.dev"
            )
        user_id = str(user_row["id"])
        portfolio_id = await self._create_portfolio(user_id)

        fake_source_id = "00000000-0000-0000-0000-000000000001"
        result = await create_cash_flow(
            portfolio_id=portfolio_id,
            amount=Decimal("1500.00"),
            source="receipt",
            source_id=fake_source_id,
        )
        assert str(result["source_id"]) == fake_source_id
        assert result["source"] == "receipt"

    async def test_list_cash_flows_pagination(self, auth_headers, client):
        """List respects limit/offset."""
        from src.cash_flows.repository import create_cash_flow, list_cash_flows
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", "test@stocklens.dev"
            )
        user_id = str(user_row["id"])
        portfolio_id = await self._create_portfolio(user_id)

        for i in range(5):
            await create_cash_flow(portfolio_id=portfolio_id, amount=Decimal(f"{i + 1}00.00"))

        rows = await list_cash_flows(portfolio_id, limit=2, offset=0)
        assert len(rows) == 2

        page2 = await list_cash_flows(portfolio_id, limit=2, offset=2)
        assert len(page2) == 2
        # Most recent first — last inserted is first
        assert page2[0]["id"] != rows[0]["id"]

    async def test_update_cash_flow_notes(self, auth_headers, client):
        """Update notes on a cash flow."""
        from src.cash_flows.repository import (
            create_cash_flow,
            get_cash_flow,
            update_cash_flow_notes,
        )
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", "test@stocklens.dev"
            )
        user_id = str(user_row["id"])
        portfolio_id = await self._create_portfolio(user_id)

        cf = await create_cash_flow(
            portfolio_id=portfolio_id, amount=Decimal("300.00"), notes="Original note"
        )
        updated = await update_cash_flow_notes(cf["id"], "Updated note")
        assert updated is True

        fetched = await get_cash_flow(cf["id"])
        assert fetched["notes"] == "Updated note"

    async def test_sum_cash_flows_empty(self, auth_headers, client):
        """Sum returns 0 when no cash flows exist."""
        from src.cash_flows.repository import sum_cash_flows
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", "test@stocklens.dev"
            )
        user_id = str(user_row["id"])
        portfolio_id = await self._create_portfolio(user_id)

        total = await sum_cash_flows(portfolio_id)
        assert total == Decimal("0")


# ──────────────────────────────────────────────────────────────────────
# Router — HTTP endpoints
# ──────────────────────────────────────────────────────────────────────


class TestCashFlowRouter:
    """HTTP-level tests for cash flows endpoints."""

    async def _create_portfolio_via_api(self, client, auth_headers) -> str:
        """Create a portfolio via API and return its ID."""
        resp = await client.post(
            "/portfolios",
            json={"name": "Cash Flow Test Portfolio"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    async def test_create_cash_flow_endpoint(self, client, auth_headers):
        """POST /portfolios/{id}/cash-flows creates a cash flow."""
        pid = await self._create_portfolio_via_api(client, auth_headers)

        resp = await client.post(
            f"/portfolios/{pid}/cash-flows",
            json={"amount": 1000.00, "source": "manual", "notes": "Test deposit"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["amount"] == 1000.00
        assert data["source"] == "manual"
        assert data["notes"] == "Test deposit"
        assert data["portfolio_id"] == pid

    async def test_create_cash_flow_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = await client.post(
            "/portfolios/00000000-0000-0000-0000-000000000000/cash-flows",
            json={"amount": 1000.00},
        )
        assert resp.status_code == 401

    async def test_create_cash_flow_zero_amount_validation(self, client, auth_headers):
        """POST with zero amount returns 422."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        resp = await client.post(
            f"/portfolios/{pid}/cash-flows",
            json={"amount": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_cash_flow_negative_amount_validation(self, client, auth_headers):
        """POST with negative amount returns 422."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        resp = await client.post(
            f"/portfolios/{pid}/cash-flows",
            json={"amount": -100},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_create_cash_flow_wrong_portfolio_returns_404(self, client, auth_headers):
        """POST to a non-existent portfolio returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.post(
            f"/portfolios/{fake_id}/cash-flows",
            json={"amount": 500.00},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_list_cash_flows_endpoint(self, client, auth_headers):
        """GET /portfolios/{id}/cash-flows returns paginated list."""
        pid = await self._create_portfolio_via_api(client, auth_headers)

        # Create 3 cash flows
        for amt in [100, 200, 300]:
            resp = await client.post(
                f"/portfolios/{pid}/cash-flows",
                json={"amount": amt, "source": "manual"},
                headers=auth_headers,
            )
            assert resp.status_code == 201

        resp = await client.get(
            f"/portfolios/{pid}/cash-flows",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["cash_flows"]) == 3
        # All amounts present (order non-deterministic within same transaction)
        amounts = {cf["amount"] for cf in data["cash_flows"]}
        assert amounts == {100, 200, 300}

    async def test_list_cash_flows_pagination_params(self, client, auth_headers):
        """GET respects limit and offset params."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        for amt in range(1, 6):
            await client.post(
                f"/portfolios/{pid}/cash-flows",
                json={"amount": amt * 100, "source": "manual"},
                headers=auth_headers,
            )

        resp = await client.get(
            f"/portfolios/{pid}/cash-flows?limit=2&offset=0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["cash_flows"]) == 2

    async def test_patch_cash_flow_notes(self, client, auth_headers):
        """PATCH /portfolios/{pid}/cash-flows/{cf_id} updates notes."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        create_resp = await client.post(
            f"/portfolios/{pid}/cash-flows",
            json={"amount": 500, "notes": "Original"},
            headers=auth_headers,
        )
        cf_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/portfolios/{pid}/cash-flows/{cf_id}",
            json={"notes": "Updated"},
            headers=auth_headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["notes"] == "Updated"

    async def test_patch_cash_flow_not_found(self, client, auth_headers):
        """PATCH on non-existent cash flow returns 404."""
        pid = await self._create_portfolio_via_api(client, auth_headers)
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/portfolios/{pid}/cash-flows/{fake_id}",
            json={"notes": "Should not work"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
