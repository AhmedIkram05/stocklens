"""
Pydantic schemas for portfolio cash flow management.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.types import DecimalAsFloat


class CashFlowCreate(BaseModel):
    """Request body for recording a new cash flow (deposit)."""

    amount: Decimal = Field(..., gt=Decimal(0), description="Deposit amount (positive only)")
    source: str = Field("receipt", description="Source of deposit: 'receipt', 'manual', 'transfer'")
    source_id: Optional[UUID] = Field(None, description="ID of the source receipt, if applicable")
    notes: Optional[str] = None


class CashFlowUpdate(BaseModel):
    """Request body for updating a cash flow (notes only — amount is immutable)."""

    notes: Optional[str] = None


class CashFlowInDB(BaseModel):
    """Full cash flow record as stored in the database."""

    model_config = {"from_attributes": True}

    id: UUID
    portfolio_id: UUID
    amount: DecimalAsFloat
    source: str
    source_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_at: datetime


class CashFlowResponse(BaseModel):
    """API response for a single cash flow."""

    id: str
    portfolio_id: str
    amount: DecimalAsFloat
    source: str
    source_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class CashFlowListResponse(BaseModel):
    """Paginated list of cash flows."""

    cash_flows: list[CashFlowResponse]
    total: int
    limit: int
    offset: int
