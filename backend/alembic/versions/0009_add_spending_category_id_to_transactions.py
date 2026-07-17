"""add spending_category_id to transactions table

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "af46e8a08234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "spending_category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("spending_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_transactions_spending_category",
        "transactions",
        ["spending_category_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_transactions_spending_category", "transactions")
    op.drop_column("transactions", "spending_category_id")
