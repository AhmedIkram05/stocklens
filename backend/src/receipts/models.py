"""
Pydantic models for receipt scanning — API payloads, extraction results, and line items.

Defines the shared data contracts used by the OCR pipeline, Bedrock LLM enhancer,
and the FastAPI router.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


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
