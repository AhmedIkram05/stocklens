"""Ensure the unique holdings index exists.

The transactions upsert relies on a unique constraint over
(portfolio_id, ticker). On databases created before that index was added,
every BUY failed with "no unique or exclusion constraint matching ON
CONFLICT". This idempotent migration guarantees the index exists.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_holdings_portfolio_ticker "
        "ON holdings (portfolio_id, ticker)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_holdings_portfolio_ticker")
