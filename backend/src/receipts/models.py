"""
Pydantic models for receipt scanning — API payloads, extraction results, and line items.

Defines the shared data contracts used by the OCR pipeline, Bedrock LLM enhancer,
and the FastAPI router.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractedItem(BaseModel):
    """A single line item from a receipt."""

    name: str
    quantity: int = 1
    price: Decimal


class ReceiptExtraction(BaseModel):
    """Structured data extracted from a receipt."""

    merchant_name: Optional[str] = None
    total: Optional[Decimal] = None
    date: Optional[date] = None
    currency: str = "GBP"
    items: list[ExtractedItem] = Field(default_factory=list)


class ReceiptScanResponse(BaseModel):
    """Response from a receipt scan — raw OCR text plus structured extraction."""

    extraction: ReceiptExtraction
    raw_text: str
    source: str  # "regex" or "bedrock"
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    error: Optional[str] = None


# ── Receipt CRUD schemas ────────────────────────────────────────────────


class ReceiptCreate(BaseModel):
    """Schema for manually creating a receipt record."""
    merchant_name: Optional[str] = None
    total_amount: Optional[Decimal] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    scanned_at: Optional[datetime] = None


class ReceiptUpdate(BaseModel):
    """Schema for updating a receipt record (edit OCR mistakes)."""
    merchant_name: Optional[str] = None
    total_amount: Optional[Decimal] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None


class ReceiptInDB(BaseModel):
    """Full receipt record as stored in the database."""
    id: str
    user_id: str
    total_amount: Optional[Decimal] = None
    merchant_name: Optional[str] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    scanned_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "ReceiptInDB":
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            total_amount=row.get("total_amount"),
            merchant_name=row.get("merchant_name"),
            category_id=str(row["category_id"]) if row.get("category_id") else None,
            ocr_raw_text=row.get("ocr_raw_text"),
            ocr_confidence=row.get("ocr_confidence"),
            line_items=row.get("line_items"),
            receipt_image_s3_key=row.get("receipt_image_s3_key"),
            scanned_at=row["scanned_at"],
            created_at=row["created_at"],
        )


class ReceiptResponse(BaseModel):
    """Receipt data returned to the client."""
    id: str
    total_amount: Optional[Decimal] = None
    merchant_name: Optional[str] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    scanned_at: datetime
    created_at: datetime


class ReceiptListResponse(BaseModel):
    receipts: list[ReceiptResponse]
    total: int
    limit: int
    offset: int
