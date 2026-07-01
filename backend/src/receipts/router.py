"""
FastAPI router for receipt scanning.

Endpoints
---------
- ``GET /receipts/health`` — OCR module health check.
- ``POST /receipts/scan`` — Upload a receipt image; returns extracted text and
  optionally LLM-enhanced structured data.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.categories.merchant_map import resolve_category
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from src.receipts.models import (
    ExtractedItem,
    ReceiptCreate,
    ReceiptExtraction,
    ReceiptListResponse,
    ReceiptResponse,
    ReceiptScanResponse,
    ReceiptUpdate,
)
from src.receipts.ocr import process_receipt

logger = structlog.get_logger()

router = APIRouter()

# ── Constants ────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/heif",
    }
)

MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/health", tags=["receipts"])
async def health() -> dict:
    """Lightweight health check — confirms the OCR module is operational."""
    return {
        "status": "ok",
        "module": "receipts",
        "tesseract_configured": settings.OCR_TESSERACT_CMD is not None,
        "bedrock_configured": bool(settings.BEDROCK_MODEL_ID),
    }


@router.post(
    "/scan",
    response_model=ReceiptScanResponse,
    status_code=status.HTTP_200_OK,
    tags=["receipts"],
    summary="Scan a receipt image and extract structured data",
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def scan_receipt(
    request: Request,  # required by slowapi's limiter
    file: UploadFile = File(...),
    current_user: UserInDB = Depends(get_current_user),
) -> ReceiptScanResponse:
    """Upload a receipt image and extract structured spending data.

    **Accepted formats:** PNG, JPEG, HEIC (max 10 MB).

    The pipeline:
    1. Validates file type and size.
    2. Preprocesses the image (grayscale → threshold → denoise → deskew).
    3. Runs Tesseract OCR (LSTM engine).
    4. Parses the raw text with regex to extract total, merchant, date, items.
    5. Persists the receipt record to the database with OCR output.
    6. Returns the structured result with source ``"regex"``.

    If regex parsing cannot find a total amount, a 422 is returned so the
    caller can prompt the user to enter the total manually.
    """
    start_time = time.perf_counter()

    # ── Validate content type ───────────────────────────────────────────────
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: {file.content_type}. "
                f"Allowed types: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
            ),
        )

    # ── Read with size guard ────────────────────────────────────────────────
    image_bytes = await file.read()
    if len(image_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum of {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    logger.info(
        "receipt_received",
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=len(image_bytes),
    )

    try:
        # ── Regex-based parsing pipeline ────────────────────────────────────
        result = process_receipt(image_bytes)

        if not result["ocr_raw_text"].strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Could not extract text from the image. "
                    "Please retake the photo with better lighting."
                ),
            )

        if result["total_amount"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Could not extract the total amount from the receipt. Please enter it manually."
                ),
            )

        elapsed = (time.perf_counter() - start_time) * 1000

        extraction = ReceiptExtraction(
            merchant_name=result["merchant_name"],
            total=result["total_amount"],
            date=result["date"],
            items=[
                ExtractedItem(
                    name=item["description"],
                    quantity=item["quantity"],
                    price=item["amount"],
                )
                for item in result["line_items"]
            ],
        )

        source = "regex"

        # ── Resolve category ────────────────────────────────────────────────
        category = None
        if extraction.merchant_name:
            matched = await resolve_category(extraction.merchant_name)
            category = matched.id if matched else None

        # ── Persist to database ─────────────────────────────────────────────
        async with connection_ctx() as conn:
            db_row = await conn.fetchrow(
                "INSERT INTO receipts "
                "(user_id, total_amount, merchant_name, category_id, ocr_raw_text, "
                " ocr_confidence, line_items, scanned_at) "
                "VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::jsonb, $8) "
                "RETURNING id, user_id, total_amount, merchant_name, category_id, "
                "ocr_raw_text, ocr_confidence, line_items, scanned_at, created_at",
                current_user.id,
                extraction.total,
                extraction.merchant_name,
                category,
                result["ocr_raw_text"],
                result["ocr_confidence"],
                json.dumps([item.model_dump() for item in extraction.items]),
                datetime.now(timezone.utc),
            )
        # image_bytes discarded after processing (never stored on device)

        logger.info(
            "receipt_scan_persisted",
            receipt_id=str(db_row["id"]),
            source=source,
            merchant=extraction.merchant_name,
            item_count=len(extraction.items),
        )

        return ReceiptScanResponse(
            extraction=extraction,
            raw_text=result["ocr_raw_text"],
            source=source,
            confidence=result["ocr_confidence"],
            processing_time_ms=round(elapsed, 2),
        )

    except ValueError as exc:
        logger.error("receipt_processing_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("receipt_processing_unexpected_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during receipt processing",
        )


# ── Receipt CRUD helpers ──────────────────────────────────────────────────


async def _fetch_receipts_for_user(user_id: str, limit: int, offset: int) -> list[dict]:
    """Return receipts for a user with pagination."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, total_amount, merchant_name, category_id, "
            "ocr_raw_text, ocr_confidence, line_items, receipt_image_s3_key, "
            "notes, transaction_date, scanned_at, created_at "
            "FROM receipts WHERE user_id = $1::uuid "
            "ORDER BY scanned_at DESC "
            "LIMIT $2 OFFSET $3",
            user_id,
            limit,
            offset,
        )
    result = [dict(r) for r in rows]
    for r in result:
        if isinstance(r.get("line_items"), str):
            r["line_items"] = json.loads(r["line_items"])
    return result


async def _count_receipts_for_user(user_id: str) -> int:
    """Return total receipt count for a user."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM receipts WHERE user_id = $1::uuid",
            user_id,
        )
    return row["cnt"] if row else 0


async def _fetch_receipt_by_id(receipt_id: str) -> dict | None:
    """Return a single receipt row by ID, or ``None``."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, total_amount, merchant_name, category_id, "
            "ocr_raw_text, ocr_confidence, line_items, receipt_image_s3_key, "
            "notes, transaction_date, scanned_at, created_at "
            "FROM receipts WHERE id = $1::uuid",
            receipt_id,
        )
    if not row:
        return None
    data = dict(row)
    data["user_id"] = str(data["user_id"])
    if isinstance(data.get("line_items"), str):
        data["line_items"] = json.loads(data["line_items"])
    return data


def _row_to_receipt_response(row: dict) -> ReceiptResponse:
    """Convert a raw DB row to a ``ReceiptResponse``."""
    line_items = row.get("line_items")
    if isinstance(line_items, str):
        line_items = json.loads(line_items)
    return ReceiptResponse(
        id=str(row["id"]),
        total_amount=row.get("total_amount"),
        merchant_name=row.get("merchant_name"),
        category_id=str(row["category_id"]) if row.get("category_id") else None,
        ocr_raw_text=row.get("ocr_raw_text"),
        ocr_confidence=row.get("ocr_confidence"),
        line_items=line_items,
        receipt_image_s3_key=row.get("receipt_image_s3_key"),
        notes=row.get("notes"),
        transaction_date=row.get("transaction_date"),
        scanned_at=row["scanned_at"],
        created_at=row["created_at"],
    )


# ── Receipt CRUD endpoints ────────────────────────────────────────────────


@router.post(
    "",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_receipt(
    request: Request,
    body: ReceiptCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> ReceiptResponse:
    """Create a receipt record manually (without scanning).

    If ``scanned_at`` is not provided, defaults to the current UTC time.
    """
    scanned_at = body.scanned_at or datetime.now(timezone.utc)

    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "INSERT INTO receipts "
            "(user_id, total_amount, merchant_name, category_id, ocr_raw_text, "
            " ocr_confidence, line_items, receipt_image_s3_key, "
            " notes, transaction_date, scanned_at) "
            "VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::jsonb, $8, $9, $10, $11) "
            "RETURNING id, user_id, total_amount, merchant_name, category_id, "
            "ocr_raw_text, ocr_confidence, line_items, receipt_image_s3_key, "
            "notes, transaction_date, scanned_at, created_at",
            current_user.id,
            body.total_amount,
            body.merchant_name,
            body.category_id,
            body.ocr_raw_text,
            body.ocr_confidence,
            json.dumps(body.line_items) if body.line_items is not None else None,
            body.receipt_image_s3_key,
            body.notes,
            body.transaction_date,
            scanned_at,
        )

    result = _row_to_receipt_response(dict(row))

    logger.info(
        "receipt_created",
        receipt_id=result.id,
        user_id=current_user.id,
        merchant=result.merchant_name,
    )

    return result


@router.get("", response_model=ReceiptListResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_receipts(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: UserInDB = Depends(get_current_user),
) -> ReceiptListResponse:
    """Return receipts for the current user with pagination.

    Supports ``?limit=50&offset=0`` query parameters (default limit 50, max 100).
    """
    limit = min(limit, 100)
    total = await _count_receipts_for_user(current_user.id)
    rows = await _fetch_receipts_for_user(current_user.id, limit, offset)
    receipts = [_row_to_receipt_response(r) for r in rows]

    return ReceiptListResponse(receipts=receipts, total=total, limit=limit, offset=offset)


@router.get("/{receipt_id}", response_model=ReceiptResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_receipt(
    request: Request,
    receipt_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> ReceiptResponse:
    """Return a single receipt by ID (must belong to current user)."""
    row = await _fetch_receipt_by_id(receipt_id)
    if row is None or row["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        )

    return _row_to_receipt_response(row)


@router.put("/{receipt_id}", response_model=ReceiptResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_receipt(
    request: Request,
    receipt_id: UUID,
    body: ReceiptUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> ReceiptResponse:
    """Update a receipt (e.g. fix OCR mistakes). Must belong to current user."""
    existing = await _fetch_receipt_by_id(receipt_id)
    if existing is None or existing["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        )

    # Build dynamic SET clause for provided fields
    set_clauses = []
    params: list = []
    idx = 1
    field_map = {
        "merchant_name": body.merchant_name,
        "total_amount": body.total_amount,
        "category_id": body.category_id,
        "ocr_raw_text": body.ocr_raw_text,
        "ocr_confidence": body.ocr_confidence,
        "line_items": body.line_items,
        "receipt_image_s3_key": body.receipt_image_s3_key,
        "notes": body.notes,
        "transaction_date": body.transaction_date,
    }

    for col, val in field_map.items():
        if val is not None:
            if col == "category_id":
                set_clauses.append(f"{col} = ${idx}::uuid")
            elif col == "line_items":
                set_clauses.append(f"{col} = ${idx}::jsonb")
                val = json.dumps(val)
            elif col == "ocr_confidence":
                set_clauses.append(f"{col} = ${idx}::real")
            elif col == "total_amount":
                set_clauses.append(f"{col} = ${idx}::numeric")
            elif col == "transaction_date":
                set_clauses.append(f"{col} = ${idx}::date")
            else:
                set_clauses.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

    if not set_clauses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for update",
        )

    set_clauses.append(f"scanned_at = ${idx}")
    params.append(existing["scanned_at"])
    idx += 1

    query = (
        "UPDATE receipts SET "
        + ", ".join(set_clauses)
        + f" WHERE id = ${idx}::uuid AND user_id = ${idx + 1}::uuid "
        "RETURNING id, user_id, total_amount, merchant_name, category_id, "
        "ocr_raw_text, ocr_confidence, line_items, receipt_image_s3_key, "
        "notes, transaction_date, scanned_at, created_at"
    )
    params.extend([receipt_id, current_user.id])

    async with connection_ctx() as conn:
        row = await conn.fetchrow(query, *params)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receipt not found",
            )

    logger.info(
        "receipt_updated",
        receipt_id=receipt_id,
        user_id=current_user.id,
    )
    return _row_to_receipt_response(dict(row))


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_receipt(
    request: Request,
    receipt_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    """Delete a receipt (must belong to current user)."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "DELETE FROM receipts WHERE id = $1::uuid AND user_id = $2::uuid",
            receipt_id,
            current_user.id,
        )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found",
        )

    logger.info(
        "receipt_deleted",
        receipt_id=receipt_id,
        user_id=current_user.id,
    )
