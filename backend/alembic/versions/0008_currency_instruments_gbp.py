"""Add currency handling: instruments table + GBP-normalised columns.

Stocks trade in currencies other than GBP (USD/EUR/...). This migration
introduces:

* ``instruments`` — ticker → (currency, exchange) reference table, resolved
  server-side from the market data provider.
* ``transactions.currency`` / ``fx_rate_to_gbp`` / ``total_amount_gbp``
* ``holdings.currency`` / ``fx_rate_to_gbp`` / ``average_cost_basis_gbp``

``*_gbp`` is the GBP-normalised parallel of the native money column so that
``SUM`` over mixed-currency rows stays valid without an FX join at query time.
Existing rows are all GBP (the app was GBP-only), so they are backfilled to
GBP with fx_rate_to_gbp = 1.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── instruments reference table ───────────────────────────────────────────
    op.create_table(
        "instruments",
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="GBP"),
        sa.Column("exchange", sa.String(20), nullable=True),
    )

    # ── transactions: currency + GBP-normalised parallel column ──────────────
    op.add_column(
        "transactions",
        sa.Column("currency", sa.String(8), nullable=False, server_default="GBP"),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "fx_rate_to_gbp",
            sa.Numeric(18, 10),
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("total_amount_gbp", sa.Numeric(24, 6), nullable=True),
    )
    # server_defaults only apply to new rows; backfill the existing GBP data.
    op.execute(
        "UPDATE transactions SET total_amount_gbp = total_amount WHERE total_amount_gbp IS NULL"
    )
    op.execute("ALTER TABLE transactions ALTER COLUMN total_amount_gbp SET NOT NULL")

    # ── holdings: currency + GBP-normalised parallel column ──────────────────
    op.add_column(
        "holdings",
        sa.Column("currency", sa.String(8), nullable=False, server_default="GBP"),
    )
    op.add_column(
        "holdings",
        sa.Column(
            "fx_rate_to_gbp",
            sa.Numeric(18, 10),
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "holdings",
        sa.Column("average_cost_basis_gbp", sa.Numeric(12, 4), nullable=True),
    )
    op.execute(
        "UPDATE holdings SET average_cost_basis_gbp = average_cost_basis "
        "WHERE average_cost_basis_gbp IS NULL"
    )
    op.execute("ALTER TABLE holdings ALTER COLUMN average_cost_basis_gbp SET NOT NULL")


def downgrade() -> None:
    op.drop_column("holdings", "average_cost_basis_gbp")
    op.drop_column("holdings", "fx_rate_to_gbp")
    op.drop_column("holdings", "currency")

    op.drop_column("transactions", "total_amount_gbp")
    op.drop_column("transactions", "fx_rate_to_gbp")
    op.drop_column("transactions", "currency")

    op.drop_table("instruments")
