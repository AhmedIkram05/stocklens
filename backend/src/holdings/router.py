"""
FastAPI router for holdings CRUD.

Endpoints use absolute paths since holdings are nested under portfolios and
also have standalone endpoints:
    - ``POST   /portfolios/{portfolio_id}/holdings``   — add a holding
    - ``GET    /portfolios/{portfolio_id}/holdings``   — list holdings
    - ``GET    /holdings/{holding_id}``                — get a holding
    - ``PUT    /holdings/{holding_id}``                — update a holding
    - ``DELETE /holdings/{holding_id}``                — delete a holding
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.holdings.schemas import (
    HoldingCreate,
    HoldingListResponse,
    HoldingResponse,
    HoldingUpdate,
)
from src.limiter import limiter

logger = structlog.get_logger()

router = APIRouter()


async def _verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


async def _verify_holding_in_portfolio(
    portfolio_id: str, holding_id: str, user_id: str
) -> dict | None:
    """Return the holding row if it exists under the portfolio and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT h.id, h.portfolio_id, h.ticker, h.shares, "
            "h.average_cost_basis, h.created_at, h.updated_at "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.id = $1::uuid AND h.portfolio_id = $2::uuid AND p.user_id = $3::uuid",
            holding_id,
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


async def _fetch_holdings_from_db(portfolio_id: str, user_id: str) -> list[dict]:
    """Return all holdings for a portfolio, scoped to the current user."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT h.id, h.portfolio_id, h.ticker, h.shares, "
            "h.average_cost_basis, h.created_at, h.updated_at "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.portfolio_id = $1::uuid AND p.user_id = $2::uuid "
            "ORDER BY h.ticker",
            portfolio_id,
            user_id,
        )
    return [dict(r) for r in rows]


async def _fetch_holding_by_id(holding_id: str, user_id: str) -> dict | None:
    """Return a single holding row, verifying portfolio ownership via JOIN."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT h.id, h.portfolio_id, h.ticker, h.shares, "
            "h.average_cost_basis, h.created_at, h.updated_at "
            "FROM holdings h "
            "JOIN portfolios p ON p.id = h.portfolio_id "
            "WHERE h.id = $1::uuid AND p.user_id = $2::uuid",
            holding_id,
            user_id,
        )
    return dict(row) if row else None


def _row_to_response(row: dict) -> HoldingResponse:
    """Convert a raw DB row to a ``HoldingResponse``."""
    return HoldingResponse(
        id=str(row["id"]),
        portfolio_id=str(row["portfolio_id"]),
        ticker=row["ticker"],
        shares=row["shares"],
        average_cost_basis=row["average_cost_basis"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post(
    "/portfolios/{portfolio_id}/holdings",
    response_model=HoldingResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_holding(
    request: Request,
    portfolio_id: UUID,
    body: HoldingCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingResponse:
    """Add a holding to a portfolio (portfolio must belong to current user)."""
    portfolio = await _verify_portfolio_ownership(portfolio_id, current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    try:
        async with connection_ctx() as conn:
            row = await conn.fetchrow(
                "INSERT INTO holdings (portfolio_id, ticker, shares, average_cost_basis) "
                "VALUES ($1::uuid, $2, $3::numeric, $4::numeric) "
                "RETURNING id, portfolio_id, ticker, shares, average_cost_basis, "
                "created_at, updated_at",
                portfolio_id,
                body.ticker,
                body.shares,
                body.average_cost_basis,
            )
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A holding with this ticker already exists in this portfolio",
        )

    result = dict(row)
    logger.info(
        "holding_created",
        user_id=current_user.id,
        holding_id=str(result["id"]),
        portfolio_id=portfolio_id,
    )
    return _row_to_response(result)


@router.get(
    "/portfolios/{portfolio_id}/holdings",
    response_model=HoldingListResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_holdings(
    request: Request,
    portfolio_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingListResponse:
    """Return all holdings for a portfolio (portfolio must belong to current user)."""
    portfolio = await _verify_portfolio_ownership(portfolio_id, current_user.id)
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    rows = await _fetch_holdings_from_db(portfolio_id, current_user.id)
    holdings = [_row_to_response(r) for r in rows]
    return HoldingListResponse(holdings=holdings, total=len(holdings))


@router.get("/holdings/{holding_id}", response_model=HoldingResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_holding(
    request: Request,
    holding_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingResponse:
    """Return a single holding by ID (verified through portfolio ownership)."""
    row = await _fetch_holding_by_id(holding_id, current_user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )
    return _row_to_response(row)


@router.put("/holdings/{holding_id}", response_model=HoldingResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_holding(
    request: Request,
    holding_id: UUID,
    body: HoldingUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingResponse:
    """Update a holding's shares and/or average_cost_basis."""
    if body.shares is None and body.average_cost_basis is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for update",
        )

    set_clauses = []
    params: list = []
    idx = 1

    if body.shares is not None:
        set_clauses.append(f"shares = ${idx}::numeric")
        params.append(body.shares)
        idx += 1

    if body.average_cost_basis is not None:
        set_clauses.append(f"average_cost_basis = ${idx}::numeric")
        params.append(body.average_cost_basis)
        idx += 1

    set_clauses.append("updated_at = now()")
    params.append(holding_id)
    params.append(current_user.id)

    query = (
        "UPDATE holdings SET "
        + ", ".join(set_clauses)
        + " FROM portfolios p"
        + f" WHERE holdings.id = ${idx}::uuid"
        + " AND p.id = holdings.portfolio_id"
        + f" AND p.user_id = ${idx + 1}::uuid"
        + " RETURNING holdings.id, holdings.portfolio_id, holdings.ticker,"
        + " holdings.shares, holdings.average_cost_basis,"
        + " holdings.created_at, holdings.updated_at"
    )

    async with connection_ctx() as conn:
        row = await conn.fetchrow(query, *params)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )

    logger.info(
        "holding_updated",
        user_id=current_user.id,
        holding_id=holding_id,
    )
    return _row_to_response(dict(row))


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_holding(
    request: Request,
    holding_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    """Delete a holding (verified through portfolio ownership)."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "DELETE FROM holdings h "
            "USING portfolios p "
            "WHERE h.id = $1::uuid "
            "AND p.id = h.portfolio_id "
            "AND p.user_id = $2::uuid",
            holding_id,
            current_user.id,
        )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )

    logger.info(
        "holding_deleted",
        user_id=current_user.id,
        holding_id=holding_id,
    )


# ── Nested endpoints (spec-compliant paths) ─────────────────────────────


@router.get(
    "/portfolios/{portfolio_id}/holdings/{holding_id}",
    response_model=HoldingResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_portfolio_holding(
    request: Request,
    portfolio_id: UUID,
    holding_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingResponse:
    """Return a single holding nested under a portfolio (spec-compliant path)."""
    row = await _verify_holding_in_portfolio(portfolio_id, holding_id, current_user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )
    return _row_to_response(row)


@router.put(
    "/portfolios/{portfolio_id}/holdings/{holding_id}",
    response_model=HoldingResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_portfolio_holding(
    request: Request,
    portfolio_id: UUID,
    holding_id: UUID,
    body: HoldingUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> HoldingResponse:
    """Update a holding nested under a portfolio (spec-compliant path)."""
    existing = await _verify_holding_in_portfolio(portfolio_id, holding_id, current_user.id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )

    if body.shares is None and body.average_cost_basis is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for update",
        )

    set_clauses = []
    params: list = []
    idx = 1

    if body.shares is not None:
        set_clauses.append(f"shares = ${idx}::numeric")
        params.append(body.shares)
        idx += 1

    if body.average_cost_basis is not None:
        set_clauses.append(f"average_cost_basis = ${idx}::numeric")
        params.append(body.average_cost_basis)
        idx += 1

    set_clauses.append("updated_at = now()")
    params.append(holding_id)

    query = (
        "UPDATE holdings SET "
        + ", ".join(set_clauses)
        + f" WHERE id = ${idx}::uuid "
        + "RETURNING id, portfolio_id, ticker, shares, average_cost_basis, "
        + "created_at, updated_at"
    )

    async with connection_ctx() as conn:
        row = await conn.fetchrow(query, *params)

    logger.info(
        "holding_updated",
        user_id=current_user.id,
        holding_id=holding_id,
    )
    return _row_to_response(dict(row))


@router.delete(
    "/portfolios/{portfolio_id}/holdings/{holding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_portfolio_holding(
    request: Request,
    portfolio_id: UUID,
    holding_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    """Delete a holding nested under a portfolio (spec-compliant path)."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "DELETE FROM holdings h "
            "USING portfolios p "
            "WHERE h.id = $1::uuid "
            "AND h.portfolio_id = $2::uuid "
            "AND p.id = h.portfolio_id "
            "AND p.user_id = $3::uuid",
            holding_id,
            portfolio_id,
            current_user.id,
        )

    if result == "DELETE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found",
        )

    logger.info(
        "holding_deleted",
        user_id=current_user.id,
        holding_id=holding_id,
    )
