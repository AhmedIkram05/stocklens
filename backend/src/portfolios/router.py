"""
FastAPI router for portfolio CRUD.

Endpoints:
    - ``POST   /portfolios``        — create a portfolio
    - ``GET    /portfolios``        — list current user's portfolios
    - ``GET    /portfolios/{id}``   — get a single portfolio
    - ``PUT    /portfolios/{id}``   — update a portfolio
    - ``DELETE /portfolios/{id}``   — delete a portfolio
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from src.portfolios.schemas import (
    PortfolioCreate,
    PortfolioListResponse,
    PortfolioResponse,
    PortfolioUpdate,
)

logger = structlog.get_logger()

router = APIRouter()


async def _fetch_portfolios_from_db(user_id: str) -> list[dict]:
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, name, description, created_at, updated_at "
            "FROM portfolios WHERE user_id = $1::uuid ORDER BY created_at DESC",
            user_id,
        )
    return [dict(r) for r in rows]


async def _fetch_portfolio_by_id(portfolio_id: str, user_id: str) -> dict | None:
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, name, description, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


def _row_to_response(row: dict) -> PortfolioResponse:
    return PortfolioResponse(
        id=str(row["id"]),
        name=row["name"],
        description=row.get("description"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=PortfolioListResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_portfolios(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioListResponse:
    """Return all portfolios belonging to the current user."""
    rows = await _fetch_portfolios_from_db(current_user.id)
    portfolios = [_row_to_response(r) for r in rows]
    return PortfolioListResponse(portfolios=portfolios, total=len(portfolios))


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_portfolio(
    request: Request,
    body: PortfolioCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioResponse:
    """Create a new portfolio for the current user."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "INSERT INTO portfolios (user_id, name, description) "
            "VALUES ($1::uuid, $2, $3) "
            "RETURNING id, user_id, name, description, created_at, updated_at",
            current_user.id,
            body.name,
            body.description,
        )

    result = dict(row)
    logger.info(
        "portfolio_created",
        user_id=current_user.id,
        portfolio_id=str(result["id"]),
    )
    return _row_to_response(result)


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_portfolio(
    request: Request,
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioResponse:
    """Return a single portfolio by ID (must belong to current user)."""
    row = await _fetch_portfolio_by_id(portfolio_id, current_user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )
    return _row_to_response(row)


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_portfolio(
    request: Request,
    portfolio_id: str,
    body: PortfolioUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> PortfolioResponse:
    """Update a portfolio's name and/or description."""
    if body.name is None and body.description is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for update",
        )

    set_clauses = []
    params: list = []
    idx = 1

    if body.name is not None:
        set_clauses.append(f"name = ${idx}")
        params.append(body.name)
        idx += 1

    if body.description is not None:
        set_clauses.append(f"description = ${idx}")
        params.append(body.description)
        idx += 1

    set_clauses.append("updated_at = now()")
    params.extend([portfolio_id, current_user.id])

    query = (
        "UPDATE portfolios SET "
        + ", ".join(set_clauses)
        + f" WHERE id = ${idx}::uuid AND user_id = ${idx + 1}::uuid "
        "RETURNING id, user_id, name, description, created_at, updated_at"
    )

    async with connection_ctx() as conn:
        row = await conn.fetchrow(query, *params)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    logger.info(
        "portfolio_updated",
        user_id=current_user.id,
        portfolio_id=portfolio_id,
    )
    return _row_to_response(dict(row))


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_portfolio(
    request: Request,
    portfolio_id: str,
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    """Delete a portfolio (must belong to current user)."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "DELETE FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            current_user.id,
        )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    logger.info(
        "portfolio_deleted",
        user_id=current_user.id,
        portfolio_id=portfolio_id,
    )
