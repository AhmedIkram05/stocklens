"""
FastAPI router for transactions CRUD.

Endpoints:
    - ``POST /portfolios/{portfolio_id}/transactions`` — create a transaction
    - ``GET /portfolios/{portfolio_id}/transactions`` — list transactions (paginated)
    - ``GET /transactions/{transaction_id}`` — get a single transaction
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from uuid import UUID
from src.transactions.schemas import (
    TransactionCreate,
    TransactionListResponse,
    TransactionResponse,
)

logger = structlog.get_logger()

router = APIRouter(tags=["transactions"])


async def _fetch_portfolio_from_db(portfolio_id: str) -> dict | None:
    """Return a portfolio row by ID, or ``None``."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, name, description, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid",
            portfolio_id,
        )
    if not row:
        return None
    data = dict(row)
    data["user_id"] = str(data["user_id"])
    return data


async def _fetch_transactions_from_db(
    portfolio_id: str, limit: int, offset: int, ticker: str | None = None
) -> list[dict]:
    """Return transactions for a portfolio with pagination.

    Supports optional ticker filtering.
    """
    if ticker:
        query = (
            "SELECT id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, transaction_date, notes, created_at "
            "FROM transactions "
            "WHERE portfolio_id = $1::uuid AND ticker = $2 "
            "ORDER BY transaction_date DESC, created_at DESC "
            "LIMIT $3 OFFSET $4"
        )
        params = (portfolio_id, ticker, limit, offset)
    else:
        query = (
            "SELECT id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, transaction_date, notes, created_at "
            "FROM transactions "
            "WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date DESC, created_at DESC "
            "LIMIT $2 OFFSET $3"
        )
        params = (portfolio_id, limit, offset)

    async with connection_ctx() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def _count_transactions_in_portfolio(
    portfolio_id: str, ticker: str | None = None
) -> int:
    """Return total transaction count for a portfolio, optionally filtered by ticker."""
    if ticker:
        query = (
            "SELECT COUNT(*) as cnt FROM transactions "
            "WHERE portfolio_id = $1::uuid AND ticker = $2"
        )
        params = (portfolio_id, ticker)
    else:
        query = "SELECT COUNT(*) as cnt FROM transactions WHERE portfolio_id = $1::uuid"
        params = (portfolio_id,)

    async with connection_ctx() as conn:
        row = await conn.fetchrow(query, *params)
    return row["cnt"] if row else 0


async def _fetch_transaction_by_id(transaction_id: str) -> dict | None:
    """Return a single transaction row by ID, or ``None``."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, transaction_date, notes, created_at "
            "FROM transactions WHERE id = $1::uuid",
            transaction_id,
        )
    if not row:
        return None
    data = dict(row)
    data["portfolio_id"] = str(data["portfolio_id"])
    return data


def _row_to_response(row: dict) -> TransactionResponse:
    """Convert a raw DB row to a ``TransactionResponse``."""
    return TransactionResponse(
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


@router.post(
    "/portfolios/{portfolio_id}/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def create_transaction(
    request: Request,
    portfolio_id: UUID,
    body: TransactionCreate,
    current_user: UserInDB = Depends(get_current_user),
) -> TransactionResponse:
    """Create a new transaction within a portfolio.

    Calculates ``total_amount = shares * price_per_share`` server-side.
    The portfolio must belong to the current user.
    """
    portfolio = await _fetch_portfolio_from_db(portfolio_id)
    if portfolio is None or portfolio["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    total_amount = body.shares * body.price_per_share

    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "INSERT INTO transactions "
            "(portfolio_id, ticker, type, shares, price_per_share, "
            " total_amount, transaction_date, notes) "
            "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8) "
            "RETURNING id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, transaction_date, notes, created_at",
            portfolio_id,
            body.ticker,
            body.type,
            body.shares,
            body.price_per_share,
            total_amount,
            body.transaction_date,
            body.notes,
        )

    result = _row_to_response(dict(row))

    logger.info(
        "transaction_created",
        transaction_id=result.id,
        portfolio_id=portfolio_id,
        ticker=result.ticker,
        type=result.type,
        user_id=current_user.id,
    )

    return result


@router.get(
    "/portfolios/{portfolio_id}/transactions",
    response_model=TransactionListResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def list_transactions(
    request: Request,
    portfolio_id: UUID,
    limit: int = 50,
    offset: int = 0,
    ticker: str | None = None,
    current_user: UserInDB = Depends(get_current_user),
) -> TransactionListResponse:
    """List transactions for a portfolio with pagination.

    Supports ``?limit=50&offset=0`` query parameters (default limit 50, max 100).
    Optionally filter by ``?ticker=AAPL``.
    """
    portfolio = await _fetch_portfolio_from_db(portfolio_id)
    if portfolio is None or portfolio["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )

    limit = min(limit, 100)  # max 100
    total = await _count_transactions_in_portfolio(portfolio_id, ticker)
    rows = await _fetch_transactions_from_db(portfolio_id, limit, offset, ticker)
    transactions = [_row_to_response(r) for r in rows]

    return TransactionListResponse(
        transactions=transactions,
        total=total,
        page=(offset // limit) + 1 if limit > 0 else 1,
        page_size=limit,
    )


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_transaction(
    request: Request,
    transaction_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> TransactionResponse:
    """Return a single transaction by ID.

    Verifies access through the portfolio ownership chain.
    """
    row = await _fetch_transaction_by_id(transaction_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    portfolio = await _fetch_portfolio_from_db(str(row["portfolio_id"]))
    if portfolio is None or portfolio["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    return _row_to_response(row)


@router.get(
    "/portfolios/{portfolio_id}/transactions/{transaction_id}",
    response_model=TransactionResponse,
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_portfolio_transaction(
    request: Request,
    portfolio_id: UUID,
    transaction_id: UUID,
    current_user: UserInDB = Depends(get_current_user),
) -> TransactionResponse:
    """Return a single transaction nested under a portfolio (spec-compliant path)."""
    row = await _fetch_transaction_by_id(transaction_id)
    if row is None or str(row["portfolio_id"]) != str(portfolio_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    portfolio = await _fetch_portfolio_from_db(str(row["portfolio_id"]))
    if portfolio is None or portfolio["user_id"] != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    return _row_to_response(row)
