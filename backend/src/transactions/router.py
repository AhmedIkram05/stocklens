"""
FastAPI router for transactions CRUD.

Endpoints:
    - ``POST /portfolios/{portfolio_id}/transactions`` — create a transaction
    - ``GET /portfolios/{portfolio_id}/transactions`` — list transactions (paginated)
    - ``GET /transactions/{transaction_id}`` — get a single transaction
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import UserInDB
from src.config import settings
from src.database.connection import connection_ctx
from src.limiter import limiter
from src.market.fx import get_fx_rate_to_gbp, resolve_instrument
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
            "total_amount, currency, total_amount_gbp, transaction_date, notes, created_at "
            "FROM transactions "
            "WHERE portfolio_id = $1::uuid AND ticker = $2 "
            "ORDER BY transaction_date DESC, created_at DESC "
            "LIMIT $3 OFFSET $4"
        )
        params = (portfolio_id, ticker, limit, offset)
    else:
        query = (
            "SELECT id, portfolio_id, ticker, type, shares, price_per_share, "
            "total_amount, currency, total_amount_gbp, transaction_date, notes, created_at "
            "FROM transactions "
            "WHERE portfolio_id = $1::uuid "
            "ORDER BY transaction_date DESC, created_at DESC "
            "LIMIT $2 OFFSET $3"
        )
        params = (portfolio_id, limit, offset)

    async with connection_ctx() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


async def _count_transactions_in_portfolio(portfolio_id: str, ticker: str | None = None) -> int:
    """Return total transaction count for a portfolio, optionally filtered by ticker."""
    if ticker:
        query = (
            "SELECT COUNT(*) as cnt FROM transactions WHERE portfolio_id = $1::uuid AND ticker = $2"
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
            "total_amount, currency, total_amount_gbp, transaction_date, notes, created_at "
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
        currency=row.get("currency", "GBP"),
        total_amount_gbp=row.get("total_amount_gbp"),
        transaction_date=row["transaction_date"],
        notes=row.get("notes"),
        created_at=row["created_at"],
    )


async def _apply_buy_to_holdings(
    conn, portfolio_id, ticker, shares, price, currency, fx_rate_to_gbp
) -> None:
    """Insert a new holding or update an existing one with a weighted-average cost basis.

    Stores the native ``average_cost_basis`` plus its GBP-normalised parallel
    ``average_cost_basis_gbp`` (native × today's ``fx_rate_to_gbp``).
    """
    existing = await conn.fetchrow(
        "SELECT shares, average_cost_basis FROM holdings "
        "WHERE portfolio_id = $1::uuid AND ticker = $2",
        portfolio_id,
        ticker,
    )
    if existing is None:
        await conn.execute(
            "INSERT INTO holdings "
            "(portfolio_id, ticker, shares, average_cost_basis, currency, "
            " fx_rate_to_gbp, average_cost_basis_gbp) "
            "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)",
            portfolio_id,
            ticker,
            shares,
            price,
            currency,
            fx_rate_to_gbp,
            price * fx_rate_to_gbp,
        )
        return
    new_shares = existing["shares"] + shares
    new_cost = (existing["shares"] * existing["average_cost_basis"] + shares * price) / new_shares
    await conn.execute(
        "UPDATE holdings SET shares = $3, average_cost_basis = $4, "
        "currency = $5, fx_rate_to_gbp = $6, average_cost_basis_gbp = $7, "
        "updated_at = now() "
        "WHERE portfolio_id = $1::uuid AND ticker = $2",
        portfolio_id,
        ticker,
        new_shares,
        new_cost,
        currency,
        fx_rate_to_gbp,
        new_cost * fx_rate_to_gbp,
    )


async def _apply_sell_to_holdings(conn, portfolio_id, ticker, shares) -> None:
    """Reduce a holding on SELL. Rejects selling more shares than currently held."""
    current = await conn.fetchval(
        "SELECT shares FROM holdings WHERE portfolio_id = $1::uuid AND ticker = $2",
        portfolio_id,
        ticker,
    )
    if current is None or current < shares:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot sell more shares than currently held.",
        )
    await conn.execute(
        "UPDATE holdings SET shares = shares - $3, updated_at = now() "
        "WHERE portfolio_id = $1::uuid AND ticker = $2",
        portfolio_id,
        ticker,
        shares,
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

    # Resolve native currency + today's GBP FX rate for this ticker.
    currency, _ = await resolve_instrument(body.ticker)
    fx_rate_to_gbp = await get_fx_rate_to_gbp(currency)
    total_amount_gbp = total_amount * fx_rate_to_gbp

    async with connection_ctx() as conn:
        # Server-side affordability guard for BUY (free cash = deposits - net invested, all GBP)
        if body.type == "BUY":
            total_deposits = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
                portfolio_id,
            )
            net_invested_gbp = await conn.fetchval(
                "SELECT COALESCE(SUM(CASE WHEN type = 'BUY' THEN total_amount_gbp "
                "WHEN type = 'SELL' THEN -total_amount_gbp ELSE 0 END), 0) "
                "FROM transactions WHERE portfolio_id = $1::uuid",
                portfolio_id,
            )
            free_cash = Decimal(str(total_deposits)) - Decimal(str(net_invested_gbp))
            if total_amount_gbp > free_cash:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Insufficient funds: this purchase costs "
                        f"{total_amount_gbp} GBP but only {free_cash} GBP is available."
                    ),
                )

        # Atomic: transaction row + holdings update commit together.
        # Check is_in_transaction() to avoid nested tx error in tests
        # (tests wrap each test in BEGIN/ROLLBACK).
        if conn.is_in_transaction():
            row = await conn.fetchrow(
                "INSERT INTO transactions "
                "(portfolio_id, ticker, type, shares, price_per_share, "
                " total_amount, currency, fx_rate_to_gbp, total_amount_gbp, "
                " transaction_date, notes) "
                "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
                "RETURNING id, portfolio_id, ticker, type, shares, price_per_share, "
                "total_amount, currency, fx_rate_to_gbp, total_amount_gbp, "
                "transaction_date, notes, created_at",
                portfolio_id,
                body.ticker,
                body.type,
                body.shares,
                body.price_per_share,
                total_amount,
                currency,
                fx_rate_to_gbp,
                total_amount_gbp,
                body.transaction_date,
                body.notes,
            )

            # Keep holdings in sync with transactions
            if body.type == "BUY":
                await _apply_buy_to_holdings(
                    conn,
                    portfolio_id,
                    body.ticker,
                    body.shares,
                    body.price_per_share,
                    currency,
                    fx_rate_to_gbp,
                )
            elif body.type == "SELL":
                await _apply_sell_to_holdings(conn, portfolio_id, body.ticker, body.shares)
        else:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO transactions "
                    "(portfolio_id, ticker, type, shares, price_per_share, "
                    " total_amount, currency, fx_rate_to_gbp, total_amount_gbp, "
                    " transaction_date, notes) "
                    "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
                    "RETURNING id, portfolio_id, ticker, type, shares, price_per_share, "
                    "total_amount, currency, fx_rate_to_gbp, total_amount_gbp, "
                    "transaction_date, notes, created_at",
                    portfolio_id,
                    body.ticker,
                    body.type,
                    body.shares,
                    body.price_per_share,
                    total_amount,
                    currency,
                    fx_rate_to_gbp,
                    total_amount_gbp,
                    body.transaction_date,
                    body.notes,
                )

                # Keep holdings in sync with transactions
                if body.type == "BUY":
                    await _apply_buy_to_holdings(
                        conn,
                        portfolio_id,
                        body.ticker,
                        body.shares,
                        body.price_per_share,
                        currency,
                        fx_rate_to_gbp,
                    )
                elif body.type == "SELL":
                    await _apply_sell_to_holdings(conn, portfolio_id, body.ticker, body.shares)

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
