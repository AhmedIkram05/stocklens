"""
FastAPI router for portfolio cash flow management.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.cash_flows.repository import (
    count_cash_flows,
    create_cash_flow,
    get_cash_flow,
    list_cash_flows,
    update_cash_flow_notes,
)
from src.cash_flows.schemas import (
    CashFlowCreate,
    CashFlowListResponse,
    CashFlowResponse,
    CashFlowUpdate,
)
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter

logger = structlog.get_logger()

router = APIRouter()


async def _verify_portfolio_ownership(portfolio_id: str, user_id: str) -> dict | None:
    """Return the portfolio row if it exists and belongs to *user_id*."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, user_id, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None


@router.get("/portfolios/{portfolio_id}/cash-flows", response_model=CashFlowListResponse)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_cash_flows_endpoint(
    request: Request,
    portfolio_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowListResponse:
    """List cash flows for a portfolio (most recent first)."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    rows = await list_cash_flows(str(portfolio_id), limit=limit, offset=offset)
    total = await count_cash_flows(str(portfolio_id))

    return CashFlowListResponse(
        cash_flows=[
            CashFlowResponse(
                id=str(r["id"]),
                portfolio_id=str(r["portfolio_id"]),
                amount=Decimal(r["amount"]),
                source=r["source"],
                source_id=str(r["source_id"]) if r.get("source_id") else None,
                notes=r.get("notes"),
                created_at=r["created_at"],
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/portfolios/{portfolio_id}/cash-flows",
    response_model=CashFlowResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_cash_flow_endpoint(
    request: Request,
    portfolio_id: UUID,
    body: CashFlowCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowResponse:
    """Record a cash flow (deposit) into a portfolio."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    row = await create_cash_flow(
        portfolio_id=str(portfolio_id),
        amount=Decimal(str(body.amount)),
        source=body.source,
        source_id=str(body.source_id) if body.source_id else None,
        notes=body.notes,
    )
    logger.info("cash_flow_created", portfolio_id=str(portfolio_id), amount=body.amount)

    return CashFlowResponse(
        id=str(row["id"]),
        portfolio_id=str(row["portfolio_id"]),
        amount=Decimal(row["amount"]),
        source=row["source"],
        source_id=str(row["source_id"]) if row.get("source_id") else None,
        notes=row.get("notes"),
        created_at=row["created_at"],
    )


@router.patch(
    "/portfolios/{portfolio_id}/cash-flows/{cash_flow_id}",
    response_model=CashFlowResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def update_cash_flow_endpoint(
    request: Request,
    portfolio_id: UUID,
    cash_flow_id: UUID,
    body: CashFlowUpdate,
    current_user: UserInDB = Depends(get_current_user),
) -> CashFlowResponse:
    """Update notes on a cash flow (amount is immutable)."""
    portfolio = await _verify_portfolio_ownership(str(portfolio_id), current_user.id)
    if portfolio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    existing = await get_cash_flow(str(cash_flow_id))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cash flow not found")

    updated = await update_cash_flow_notes(str(cash_flow_id), body.notes)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update",
        )

    row = await get_cash_flow(str(cash_flow_id))
    return CashFlowResponse(
        id=str(row["id"]),
        portfolio_id=str(row["portfolio_id"]),
        amount=Decimal(row["amount"]),
        source=row["source"],
        source_id=str(row["source_id"]) if row.get("source_id") else None,
        notes=row.get("notes"),
        created_at=row["created_at"],
    )
