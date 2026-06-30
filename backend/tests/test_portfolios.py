"""
Tests for portfolio CRUD endpoints.

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

import httpx
import pytest


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreatePortfolio:
    """POST /portfolios"""

    async def test_create_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Creating a portfolio with valid data returns 201."""
        response = await client.post(
            "/portfolios",
            json={"name": "Retirement Fund", "description": "Long-term savings"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Retirement Fund"
        assert data["description"] == "Long-term savings"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_minimal(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Creating a portfolio with only a name succeeds."""
        response = await client.post(
            "/portfolios",
            json={"name": "Minimal"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Minimal"
        assert response.json()["description"] is None

    async def test_create_unauthenticated(self, client: httpx.AsyncClient):
        """Creating a portfolio without auth returns 401."""
        response = await client.post(
            "/portfolios",
            json={"name": "No Auth"},
        )
        assert response.status_code == 401

    async def test_create_empty_name(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Creating a portfolio with empty name returns 422."""
        response = await client.post(
            "/portfolios",
            json={"name": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422


# ── List ────────────────────────────────────────────────────────────────────


class TestListPortfolios:
    """GET /portfolios"""

    async def test_list_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Listing returns all portfolios for the authenticated user."""
        await client.post("/portfolios", json={"name": "P1"}, headers=auth_headers)
        await client.post("/portfolios", json={"name": "P2"}, headers=auth_headers)
        response = await client.get("/portfolios", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["portfolios"]) == 2
        names = {p["name"] for p in data["portfolios"]}
        assert names == {"P1", "P2"}

    async def test_list_empty(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """A user with no portfolios gets an empty list."""
        response = await client.get("/portfolios", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == {"portfolios": [], "total": 0}

    async def test_list_scoped_to_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Users cannot see each other's portfolios."""
        await client.post("/portfolios", json={"name": "Mine"}, headers=auth_headers)
        # Register a second user
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_token = resp2.json()["tokens"]["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}
        resp3 = await client.get("/portfolios", headers=other_headers)
        assert resp3.status_code == 200
        assert resp3.json()["total"] == 0


# ── Get ─────────────────────────────────────────────────────────────────────


class TestGetPortfolio:
    """GET /portfolios/{id}"""

    async def test_get_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Getting a portfolio by ID returns the correct portfolio."""
        created = await client.post(
            "/portfolios", json={"name": "Get Test"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        response = await client.get(f"/portfolios/{pid}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "Get Test"

    async def test_get_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Getting a non-existent portfolio returns 404."""
        response = await client.get(
            "/portfolios/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_other_user_portfolio(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Getting another user's portfolio returns 404 (not 403)."""
        created = await client.post(
            "/portfolios", json={"name": "Secret"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        # Second user
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other2@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.get(f"/portfolios/{pid}", headers=other_headers)
        assert response.status_code == 404


# ── Update ──────────────────────────────────────────────────────────────────


class TestUpdatePortfolio:
    """PUT /portfolios/{id}"""

    async def test_update_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Updating a portfolio returns the updated fields."""
        created = await client.post(
            "/portfolios", json={"name": "Old Name", "description": "Old desc"},
            headers=auth_headers,
        )
        pid = created.json()["id"]
        response = await client.put(
            f"/portfolios/{pid}",
            json={"name": "New Name", "description": "New desc"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["description"] == "New desc"

    async def test_update_partial_name_only(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Updating only the name preserves the existing description."""
        created = await client.post(
            "/portfolios", json={"name": "Original", "description": "Keep me"},
            headers=auth_headers,
        )
        pid = created.json()["id"]
        response = await client.put(
            f"/portfolios/{pid}",
            json={"name": "Renamed"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed"
        assert response.json()["description"] == "Keep me"

    async def test_update_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Updating a non-existent portfolio returns 404."""
        response = await client.put(
            "/portfolios/00000000-0000-0000-0000-000000000000",
            json={"name": "Nope"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_no_fields(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Updating with no fields returns 400."""
        created = await client.post(
            "/portfolios", json={"name": "No Update"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        response = await client.put(
            f"/portfolios/{pid}",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 400


# ── Delete ──────────────────────────────────────────────────────────────────


class TestDeletePortfolio:
    """DELETE /portfolios/{id}"""

    async def test_delete_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Deleting a portfolio returns 204."""
        created = await client.post(
            "/portfolios", json={"name": "To Delete"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        response = await client.delete(f"/portfolios/{pid}", headers=auth_headers)
        assert response.status_code == 204

    async def test_delete_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Deleting a non-existent portfolio returns 404."""
        response = await client.delete(
            "/portfolios/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_delete_other_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """Deleting another user's portfolio returns 404."""
        created = await client.post(
            "/portfolios", json={"name": "Theirs"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other3@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.delete(f"/portfolios/{pid}", headers=other_headers)
        assert response.status_code == 404

    async def test_delete_then_get(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        """After deletion, getting the portfolio returns 404."""
        created = await client.post(
            "/portfolios", json={"name": "Gone"}, headers=auth_headers,
        )
        pid = created.json()["id"]
        await client.delete(f"/portfolios/{pid}", headers=auth_headers)
        response = await client.get(f"/portfolios/{pid}", headers=auth_headers)
        assert response.status_code == 404
