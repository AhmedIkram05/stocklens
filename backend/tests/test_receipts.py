"""
Tests for receipts CRUD endpoints.

All database access runs inside the per-test transaction provided by
``conftest._test_db`` so no data leaks between tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx


async def _create_receipt(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    **overrides,
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

    async def test_create_with_line_items(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
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

    async def test_list_scoped_to_user(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
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


# ── Health endpoints ────────────────────────────────────────────────────────


class TestHealthEndpoints:
    """GET /receipts/health and /receipts/cascade/health"""

    async def test_health_endpoint(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        response = await client.get("/receipts/health", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["module"] == "receipts"
        assert "tesseract_configured" in data
        assert "bedrock_configured" in data

    @patch("src.receipts.router.get_redis", new_callable=AsyncMock)
    async def test_cascade_health_degraded_bedrock(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Bedrock fails (no AWS creds in CI) -> degraded. Redis mocked ok."""
        mock_redis.return_value.ping = AsyncMock(return_value=True)
        response = await client.get("/receipts/cascade/health", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # In test env bedrock will fail (no AWS creds)
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "ok"
        assert "cascade_threshold" in data

    @patch("src.receipts.router.get_redis", new_callable=AsyncMock)
    async def test_cascade_health_redis_unavailable(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value.ping.side_effect = RuntimeError("redis down")
        response = await client.get("/receipts/cascade/health", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] == "unavailable"
        assert "cascade_threshold" in data


# ── Scan endpoint (cascade OCR) ─────────────────────────────────────────────


class TestScanReceipt:
    """POST /receipts/scan — cascade OCR pipeline"""

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_success_regex_path(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        from src.receipts.cascade import FieldConfidence as CascadeFieldConfidence
        from src.receipts.models import CascadeResult, ReceiptExtraction

        mock_cascade.return_value = CascadeResult(
            raw_text="TESCO\nMilk 1.65\nTotal 15.50",
            source="regex",
            overall_confidence=0.92,
            extraction=ReceiptExtraction(
                merchant_name="TESCO",
                total=Decimal("15.50"),
                date=date(2024, 1, 15),
                items=[{"name": "Milk 2L", "quantity": 1, "price": Decimal("1.65")}],
            ),
            field_confidences={
                "merchant_name": CascadeFieldConfidence(confidence=0.9, source="regex"),
                "total": CascadeFieldConfidence(confidence=0.95, source="regex"),
            },
            discrepancies=[],
            llm_category=None,
        )

        files = {"file": ("receipt.jpg", b"fake image data", "image/jpeg")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "regex"
        assert data["confidence"] == 0.92
        assert data["extraction"]["merchant_name"] == "TESCO"
        assert float(data["extraction"]["total"]) == 15.50

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_success_cascade_path(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        from src.receipts.cascade import FieldConfidence as CascadeFieldConfidence
        from src.receipts.models import CascadeResult, ReceiptExtraction

        mock_cascade.return_value = CascadeResult(
            raw_text="BLURRY STORE\nTotal 25.00",
            source="cascade",
            overall_confidence=0.78,
            extraction=ReceiptExtraction(
                merchant_name="BLURRY STORE",
                total=Decimal("25.00"),
                date=date(2024, 2, 10),
                items=[{"name": "Item 1", "quantity": 1, "price": Decimal("25.00")}],
            ),
            field_confidences={
                "merchant_name": CascadeFieldConfidence(confidence=0.7, source="llm"),
                "total": CascadeFieldConfidence(confidence=0.85, source="regex"),
            },
            discrepancies=[{"field": "merchant_name", "regex": "BLURRY", "llm": "BLURRY STORE"}],
            llm_category="Food & Dining",
        )

        files = {"file": ("receipt.png", b"fake png data", "image/png")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "cascade"
        assert data["confidence"] == 0.78
        assert data["extraction"]["merchant_name"] == "BLURRY STORE"
        assert float(data["extraction"]["total"]) == 25.0

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_rejects_invalid_content_type(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        files = {"file": ("receipt.pdf", b"fake pdf", "application/pdf")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_rejects_oversized_file(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        # 11 MB file (limit is 10 MB)
        big_data = b"x" * (11 * 1024 * 1024)
        files = {"file": ("big.jpg", big_data, "image/jpeg")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)
        assert response.status_code == 413
        assert "exceeds maximum" in response.json()["detail"]

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_empty_ocr_text_returns_422(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        from src.receipts.models import CascadeResult, ReceiptExtraction

        mock_cascade.return_value = CascadeResult(
            raw_text="",  # empty OCR result
            source="regex",
            overall_confidence=0.1,
            extraction=ReceiptExtraction(),
            field_confidences={},
            discrepancies=[],
        )

        files = {"file": ("blank.jpg", b"blank image", "image/jpeg")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)
        assert response.status_code == 422
        assert "Could not extract text" in response.json()["detail"]

    @patch("src.receipts.router.cascade_extract", new_callable=AsyncMock)
    async def test_scan_missing_total_returns_422(
        self, mock_cascade, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        from src.receipts.models import CascadeResult, ReceiptExtraction

        mock_cascade.return_value = CascadeResult(
            raw_text="STORE\nItem 5.00\nItem 3.00",
            source="regex",
            overall_confidence=0.5,
            extraction=ReceiptExtraction(
                merchant_name="STORE",
                total=None,  # missing total
                items=[{"name": "Item", "quantity": 1, "price": Decimal("5.00")}],
            ),
            field_confidences={},
            discrepancies=[],
        )

        files = {"file": ("nototal.jpg", b"data", "image/jpeg")}
        response = await client.post("/receipts/scan", files=files, headers=auth_headers)
        assert response.status_code == 422
        assert "Could not extract the total amount" in response.json()["detail"]


# ── Enrichment status ───────────────────────────────────────────────────────


class TestEnrichmentStatus:
    """GET /receipts/{id}/enrich-status"""

    @patch("src.receipts.router.get_enrich_status", new_callable=AsyncMock)
    async def test_enrich_status_pending(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value = "pending"
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]

        response = await client.get(f"/receipts/{rid}/enrich-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["receipt_id"] == rid

    @patch("src.receipts.router.get_enrich_status", new_callable=AsyncMock)
    async def test_enrich_status_completed_from_db(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value = None  # Redis returns None, falls back to DB
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        # Update source to "cascade" to simulate completed
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            await conn.execute("UPDATE receipts SET source = 'cascade' WHERE id = $1::uuid", rid)

        response = await client.get(f"/receipts/{rid}/enrich-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["source"] == "cascade"

    @patch("src.receipts.router.get_enrich_status", new_callable=AsyncMock)
    async def test_enrich_status_failed_from_db(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value = None
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            await conn.execute("UPDATE receipts SET source = 'degraded' WHERE id = $1::uuid", rid)

        response = await client.get(f"/receipts/{rid}/enrich-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"

    @patch("src.receipts.router.get_enrich_status", new_callable=AsyncMock)
    async def test_enrich_status_not_needed(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value = None
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        from src.database.connection import connection_ctx

        async with connection_ctx() as conn:
            await conn.execute("UPDATE receipts SET source = 'regex' WHERE id = $1::uuid", rid)

        response = await client.get(f"/receipts/{rid}/enrich-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_needed"

    @patch("src.receipts.router.get_enrich_status", new_callable=AsyncMock)
    async def test_enrich_status_unknown_receipt(
        self, mock_redis, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        mock_redis.return_value = None
        response = await client.get(
            "/receipts/00000000-0000-0000-0000-000000000000/enrich-status",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unknown"


# ── Update receipt field-type branches ──────────────────────────────────────


class TestUpdateReceiptFieldTypes:
    """Edge cases in update_receipt for different field types"""

    async def test_update_line_items_jsonb(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """line_items uses ::jsonb cast (lines 590-591)"""
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={"line_items": [{"description": "New item", "amount": 10.0, "quantity": 2}]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["line_items"] is not None
        assert len(data["line_items"]) == 1
        assert data["line_items"][0]["description"] == "New item"

    async def test_update_ocr_confidence_real_cast(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """ocr_confidence uses ::real cast (line 593)"""
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={"ocr_confidence": 0.95},
            headers=auth_headers,
        )
        assert response.status_code == 200
        # Float precision - use approximate comparison
        assert abs(float(response.json()["ocr_confidence"]) - 0.95) < 0.001

    async def test_update_total_amount_numeric_cast(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """total_amount uses ::numeric cast (line 595)"""
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={"total_amount": "123.45"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert float(response.json()["total_amount"]) == 123.45

    async def test_update_transaction_date_date_cast(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """transaction_date uses ::date cast (line 597)"""
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={"transaction_date": "2024-12-25"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["transaction_date"] == "2024-12-25"

    async def test_update_no_fields_returns_400(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Empty set_clauses -> 400 (line 604-606)"""
        rcpt = await _create_receipt(client, auth_headers)
        rid = rcpt["id"]
        response = await client.put(
            f"/receipts/{rid}",
            json={},  # no fields
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "At least one field must be provided" in response.json()["detail"]

    async def test_update_nonexistent_receipt_returns_404(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """row is None after UPDATE -> 404 (line 625-628)"""
        response = await client.put(
            "/receipts/00000000-0000-0000-0000-000000000000",
            json={"merchant_name": "Ghost"},
            headers=auth_headers,
        )
        assert response.status_code == 404
