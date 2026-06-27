"""
FastAPI router for receipt scanning.

Endpoints
---------
- ``GET /receipts/health`` — OCR module health check.
- ``POST /receipts/scan`` — Upload a receipt image; returns extracted text and
  optionally LLM-enhanced structured data.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from src.config import settings
from src.limiter import limiter
from src.receipts.models import ExtractedItem, ReceiptExtraction, ReceiptScanResponse
from src.receipts.ocr import process_receipt

logger = structlog.get_logger()

router = APIRouter()

# ── Constants ────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
})

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
) -> ReceiptScanResponse:
    """Upload a receipt image and extract structured spending data.

    **Accepted formats:** PNG, JPEG, HEIC (max 10 MB).

    The pipeline:
    1. Validates file type and size.
    2. Preprocesses the image (grayscale → threshold → denoise → deskew).
    3. Runs Tesseract OCR (LSTM engine).
    4. Parses the raw text with regex to extract total, merchant, date, items.
    5. Returns the structured result with source ``"regex"``.

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
                    "Could not extract the total amount from the receipt. "
                    "Please enter it manually."
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
        logger.info(
            "receipt_scan_complete",
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
