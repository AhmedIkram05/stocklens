"""
FastAPI router for spending categories.

Endpoints:
    - ``GET /categories`` — list all available spending categories
    - ``GET /categories/{category_id}`` — get a single category by ID
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.categories.schemas import CategoryListResponse, CategoryResponse
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from uuid import UUID

logger = structlog.get_logger()

router = APIRouter()


async def _fetch_categories_from_db() -> list[dict]:
    """Return all rows from ``spending_categories`` ordered by name."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, name, description, merchant_keywords, associated_tickers "
            "FROM spending_categories ORDER BY name"
        )
    return [dict(r) for r in rows]


async def _fetch_category_by_id(category_id: str) -> dict | None:
    """Return a single category row by ID, or ``None``."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, description, merchant_keywords, associated_tickers "
            "FROM spending_categories WHERE id = $1::uuid",
            category_id,
        )
    return dict(row) if row else None


def _row_to_response(row: dict) -> CategoryResponse:
    """Convert a raw DB row to a ``CategoryResponse``."""
    keywords = row.get("merchant_keywords") or []
    if isinstance(keywords, str):
        keywords = json.loads(keywords)
    tickers = row.get("associated_tickers") or []
    if isinstance(tickers, str):
        tickers = json.loads(tickers)
    return CategoryResponse(
        id=str(row["id"]),
        name=row["name"],
        description=row.get("description"),
        merchant_keywords=keywords,
        associated_tickers=tickers,
    )


@router.get("", response_model=CategoryListResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_categories(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
) -> CategoryListResponse:
    """Return all spending categories.

    Requires authentication. Categories are ordered alphabetically by name.
    """
    rows = await _fetch_categories_from_db()
    categories = [_row_to_response(r) for r in rows]

    logger.info(
        "categories_listed",
        user_id=current_user.id,
        count=len(categories),
    )

    return CategoryListResponse(categories=categories, total=len(categories))


@router.get("/{category_id}", response_model=CategoryResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_category(
    request: Request,
    category_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> CategoryResponse:
    """Return a single spending category by ID."""
    row = await _fetch_category_by_id(category_id)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    return _row_to_response(row)
