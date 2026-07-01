"""
Pydantic schemas for holdings CRUD.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.types import DecimalAsFloat


class HoldingBase(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    shares: DecimalAsFloat = Field(..., gt=0)
    average_cost_basis: DecimalAsFloat = Field(..., ge=0)

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper()


class HoldingCreate(HoldingBase):
    pass


class HoldingUpdate(BaseModel):
    shares: Optional[DecimalAsFloat] = Field(None, gt=0)
    average_cost_basis: Optional[DecimalAsFloat] = Field(None, ge=0)


class HoldingInDB(HoldingBase):
    id: str
    portfolio_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "HoldingInDB":
        return cls(
            id=str(row["id"]),
            portfolio_id=str(row["portfolio_id"]),
            ticker=row["ticker"],
            shares=row["shares"],
            average_cost_basis=row["average_cost_basis"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class HoldingResponse(HoldingBase):
    id: str
    portfolio_id: str
    created_at: datetime
    updated_at: datetime


class HoldingListResponse(BaseModel):
    holdings: list[HoldingResponse]
    total: int
