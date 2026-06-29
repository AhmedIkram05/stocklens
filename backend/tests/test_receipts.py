"""
Tests for receipts CRUD endpoints.

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest


async def _create_receipt(
    client: httpx.AsyncClient, headers: dict[str, str], **overrides,
) -> dict:
    payload = {
        "merchant_name": "Tesco",
        "total_amount": "47.99",
        "ocr_raw_text": "TESCO STORES LTD\nMilk 1.65\nBread 1.20\nTotal 47.99",
        "ocr_confidence": 0.87,
        "line_items": [
            {"description": "Milk 2L Semi", "amount": 1.65, "quantity": 1},
            {"description": "Bread Wholemeal", "amount": 1.20, "quantity": 1},
        ],
    }
    payload.update(overrides)
    resp = await client.post("/receipts", json=payload, headers=headers)
    assert resp.status_code == 201
    return resp.json()


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreateReceipt:
    """POST /receipts"""

    async def test_create_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.post(
            "/receipts",
            json={
                "merchant_name": "Waitrose",
                "total_amount": "32.50",
                "ocr_raw_text": "Waitrose\nTotal 32.50",
                "ocr_confidence": 0.95,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["merchant_name"] == "Waitrose"
        assert float(data["total_amount"]) == 32.50
        assert "id" in data
        assert "created_at" in data

    async def test_create_with_line_items(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.post(
            "/receipts",
            json={
                "merchant_name": "Amazon",
                "total_amount": "89.99",
                "line_items": [
                    {"description": "Book", "amount": 29.99, "quantity": 1},
                    {"description": "Gadget", "amount": 60.00, "quantity": 1},
                ],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["line_items"] is not None


# ── List ────────────────────────────────────────────────────────────────────


class TestListReceipts:
    """GET /receipts"""

    async def test_list_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        await _create_receipt(client, auth_headers)
        await _create_receipt(client, auth_headers, merchant_name="Sainsbury")
        response = await client.get("/receipts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["receipts"]) == 2

    async def test_list_empty(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get("/receipts", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["receipts"] == []

    async def test_list_pagination(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        for i in range(5):
            await _create_receipt(client, auth_headers, merchant_name=f"Store{i}")
        response = await client.get("/receipts?limit=2&offset=0", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["receipts"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_list_scoped_to_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        await _create_receipt(client, auth_headers)
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.get("/receipts", headers=other_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 0


# ── Get ─────────────────────────────────────────────────────────────────────


class TestGetReceipt:
    """GET /receipts/{id}"""

    async def test_get_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.get(f"/receipts/{rid}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["id"] == rid

    async def test_get_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get(
            "/receipts/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_other_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other2@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.get(f"/receipts/{rid}", headers=other_headers)
        assert response.status_code == 404


# ── Update ──────────────────────────────────────────────────────────────────


class TestUpdateReceipt:
    """PUT /receipts/{id}"""

    async def test_update_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers, merchant_name="Old Name")
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={"merchant_name": "New Name", "total_amount": "99.99"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["merchant_name"] == "New Name"
        assert float(data["total_amount"]) == 99.99

    async def test_update_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.put(
            "/receipts/00000000-0000-0000-0000-000000000000",
            json={"merchant_name": "Nope"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_other_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other3@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.put(
            f"/receipts/{rid}",
            json={"merchant_name": "Hacker"},
            headers=other_headers,
        )
        assert response.status_code == 404


# ── Delete ──────────────────────────────────────────────────────────────────


class TestDeleteReceipt:
    """DELETE /receipts/{id}"""

    async def test_delete_success(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.delete(f"/receipts/{rid}", headers=auth_headers)
        assert response.status_code == 204

    async def test_delete_not_found(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.delete(
            "/receipts/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_delete_other_user(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        resp2 = await client.post(
            "/auth/register",
            json={"email": "other4@test.com", "password": "OtherPass123!", "full_name": "Other"},
        )
        other_headers = {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}
        response = await client.delete(f"/receipts/{rid}", headers=other_headers)
        assert response.status_code == 404

    async def test_delete_then_get(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        await client.delete(f"/receipts/{rid}", headers=auth_headers)
        response = await client.get(f"/receipts/{rid}", headers=auth_headers)
        assert response.status_code == 404
