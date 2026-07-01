"""
Pydantic schemas for transactions CRUD.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.types import DecimalAsFloat


class TransactionBase(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    type: str = Field(..., pattern=r"^(BUY|SELL)$")
    shares: DecimalAsFloat = Field(..., gt=0)
    price_per_share: DecimalAsFloat = Field(..., ge=0)
    transaction_date: date
    notes: Optional[str] = None

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper()

    @field_validator("transaction_date")
    @classmethod
    def not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("transaction_date cannot be in the future")
        return v

    @field_validator("shares")
    @classmethod
    def validate_shares(cls, v: Decimal) -> Decimal:
        if v.as_tuple().exponent < -6:
            raise ValueError("shares can have at most 6 decimal places")
        return v

    @field_validator("price_per_share")
    @classmethod
    def validate_price(cls, v: Decimal) -> Decimal:
        if v.as_tuple().exponent < -4:
            raise ValueError("price_per_share can have at most 4 decimal places")
        return v


class TransactionCreate(TransactionBase):
    pass


class TransactionInDB(TransactionBase):
    id: str
    portfolio_id: str
    total_amount: DecimalAsFloat
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "TransactionInDB":
        return cls(
            id=str(row["id"]),
            portfolio_id=str(row["portfolio_id"]),
            ticker=row["ticker"],
            type=row["type"],
            shares=row["shares"],
            price_per_share=row["price_per_share"],
            total_amount=row["total_amount"],
            transaction_date=row["transaction_date"],
            notes=row.get("notes"),
            created_at=row["created_at"],
        )


class TransactionResponse(TransactionBase):
    id: str
    portfolio_id: str
    total_amount: DecimalAsFloat
    created_at: datetime


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    page_size: int
