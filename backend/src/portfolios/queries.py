"""
Shared read layer for portfolios.

Pure database fetch helpers used by both the REST router and (Phase 3)
the GraphQL resolvers. No HTTP, no auth, no response shaping.
"""

from __future__ import annotations

from src.database.connection import connection_ctx


async def fetch_portfolios_from_db(user_id: str) -> list[dict]:
    async with connection_ctx() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, name, description, created_at, updated_at "
            "FROM portfolios WHERE user_id = $1::uuid ORDER BY created_at DESC",
            user_id,
        )
    return [dict(r) for r in rows]


async def fetch_portfolio_by_id(portfolio_id: str, user_id: str) -> dict | None:
    async with connection_ctx() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, name, description, created_at, updated_at "
            "FROM portfolios WHERE id = $1::uuid AND user_id = $2::uuid",
            portfolio_id,
            user_id,
        )
    return dict(row) if row else None
