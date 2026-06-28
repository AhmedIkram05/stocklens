"""
Pydantic schemas for spending categories.

Categories are stored in the ``spending_categories`` table and are used to
classify receipts by merchant. Each category may have associated stock
tickers for investment analysis.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class CategoryBase(BaseModel):
    """Base category fields shared across request/response schemas."""

    name: str
    description: Optional[str] = None
    merchant_keywords: list[str] = []
    associated_tickers: list[str] = []


class CategoryCreate(CategoryBase):
    """Schema for creating a new category (admin use)."""

    pass


class CategoryInDB(CategoryBase):
    """Category record as stored in the database."""

    id: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "CategoryInDB":
        """Construct from a raw asyncpg row."""
        return cls(
            id=str(row["id"]),
            name=row["name"],
            description=row.get("description"),
            merchant_keywords=row.get("merchant_keywords") or [],
            associated_tickers=row.get("associated_tickers") or [],
        )


class CategoryResponse(CategoryBase):
    """Category data returned to the client."""

    id: str


class CategoryListResponse(BaseModel):
    """List of categories returned to the client."""

    categories: list[CategoryResponse]
    total: int
