"""
Pydantic models for receipt scanning — API payloads, extraction results, and line items.

Defines the shared data contracts used by the OCR pipeline, Bedrock LLM enhancer,
and the FastAPI router.
"""

import datetime as _dt
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import Literal

from src.type_aliases import DecimalAsFloat


class ExtractedItem(BaseModel):
    """A single line item from a receipt."""

    name: str
    quantity: int = 1
    price: DecimalAsFloat


class ReceiptExtraction(BaseModel):
    """Structured data extracted from a receipt."""

    merchant_name: Optional[str] = None
    total: Optional[DecimalAsFloat] = None
    date: Optional[_dt.date] = None
    currency: str = "GBP"
    items: list[ExtractedItem] = Field(default_factory=list)


class ReceiptScanResponse(BaseModel):
    """Response from a receipt scan — raw OCR text plus structured extraction."""

    id: str
    extraction: ReceiptExtraction
    raw_text: str
    source: str  # "regex", "cascade", "degraded", or "failed"
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    error: Optional[str] = None


# ── Receipt CRUD schemas ────────────────────────────────────────────────


class ReceiptCreate(BaseModel):
    """Schema for manually creating a receipt record."""

    merchant_name: Optional[str] = None
    total_amount: Optional[DecimalAsFloat] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    notes: Optional[str] = None
    transaction_date: Optional[_dt.date] = None
    scanned_at: Optional[_dt.datetime] = None


class ReceiptUpdate(BaseModel):
    """Schema for updating a receipt record (edit OCR mistakes)."""

    merchant_name: Optional[str] = None
    total_amount: Optional[DecimalAsFloat] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    transaction_date: Optional[_dt.date] = None
    notes: Optional[str] = None


class ReceiptInDB(BaseModel):
    """Full receipt record as stored in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    total_amount: Optional[DecimalAsFloat] = None
    merchant_name: Optional[str] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    notes: Optional[str] = None
    transaction_date: Optional[_dt.date] = None
    scanned_at: _dt.datetime
    created_at: _dt.datetime

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
            notes=row.get("notes"),
            transaction_date=row.get("transaction_date"),
            scanned_at=row["scanned_at"],
            created_at=row["created_at"],
        )


class ReceiptResponse(BaseModel):
    """Receipt data returned to the client."""

    id: str
    total_amount: Optional[DecimalAsFloat] = None
    merchant_name: Optional[str] = None
    category_id: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    ocr_confidence: Optional[float] = None
    line_items: Optional[list[dict]] = None
    receipt_image_s3_key: Optional[str] = None
    notes: Optional[str] = None
    transaction_date: Optional[_dt.date] = None
    scanned_at: _dt.datetime
    created_at: _dt.datetime


class ReceiptListResponse(BaseModel):
    receipts: list[ReceiptResponse]
    total: int
    limit: int
    offset: int


# ── NLP Cascade models ──────────────────────────────────────────────────


class FieldConfidence(BaseModel):
    """An extracted field with its confidence score."""

    value: str | float | list[dict] | None = None
    confidence: float  # 0.0 – 1.0
    source: Literal["regex", "llm"]


class CascadeResult(BaseModel):
    """Result of the cascade extraction pipeline."""

    extraction: ReceiptExtraction
    field_confidences: dict[str, FieldConfidence]
    overall_confidence: float
    source: Literal["regex", "cascade", "pending_llm", "degraded", "failed"]
    discrepancies: list[dict] = Field(default_factory=list)
    raw_text: str
    llm_category: str | None = None


class EnrichStatusResponse(BaseModel):
    """Status of background LLM enrichment for a receipt."""

    receipt_id: str
    status: Literal["completed", "failed", "pending", "not_needed", "unknown"]
    source: str | None = None


class CascadeDecisionDB(BaseModel):
    """Per-receipt cascade outcome as stored in cascade_decisions table."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    receipt_id: str
    raw_text_hash: str
    regex_confidence: float
    llm_confidence: float | None = None
    chosen_source: str
    field_confidences: dict | None = None
    discrepancies: list[dict] | None = None
    processing_time_ms: int
    created_at: _dt.datetime
