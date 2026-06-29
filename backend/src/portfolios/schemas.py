"""
Pydantic schemas for portfolio CRUD.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PortfolioBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class PortfolioCreate(PortfolioBase):
    pass


class PortfolioUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class PortfolioInDB(PortfolioBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "PortfolioInDB":
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class PortfolioResponse(PortfolioBase):
    id: str
    created_at: datetime
    updated_at: datetime


class PortfolioListResponse(BaseModel):
    portfolios: list[PortfolioResponse]
    total: int
