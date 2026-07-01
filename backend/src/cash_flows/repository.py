"""
Cash flows repository — direct asyncpg queries.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from src.database.connection import connection_ctx


async def create_cash_flow(
    portfolio_id: str,
    amount: Decimal,
    source: str = "receipt",
    source_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a cash flow record and return it."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cash_flows (portfolio_id, amount, source, source_id, notes)
            VALUES ($1::uuid, $2, $3, $4::uuid, $5)
            RETURNING id, portfolio_id, amount, source, source_id, notes, created_at
            """,
            portfolio_id,
            amount,
            source,
            source_id,
            notes,
        )
    return dict(row)


async def list_cash_flows(
    portfolio_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List cash flows for a portfolio, most recent first."""
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE portfolio_id = $1::uuid "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT $2 OFFSET $3",
            portfolio_id,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def count_cash_flows(portfolio_id: str) -> int:
    """Count total cash flows for a portfolio."""
    async with connection_ctx() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )


async def get_cash_flow(id: str) -> dict[str, Any] | None:
    """Get a single cash flow by ID."""
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, portfolio_id, amount, source, source_id, notes, created_at "
            "FROM cash_flows WHERE id = $1::uuid",
            id,
        )
    return dict(row) if row else None


async def update_cash_flow_notes(id: str, notes: Optional[str]) -> bool:
    """Update notes on a cash flow. Returns True if updated."""
    async with connection_ctx() as conn:
        result = await conn.execute(
            "UPDATE cash_flows SET notes = $2 WHERE id = $1::uuid",
            id,
            notes,
        )
    return result == "UPDATE 1"


async def sum_cash_flows(portfolio_id: str) -> Decimal:
    """Return total deposits for a portfolio (SUM of all cash flows)."""
    async with connection_ctx() as conn:
        total = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM cash_flows WHERE portfolio_id = $1::uuid",
            portfolio_id,
        )
    return Decimal(str(total))
