"""Add notes and transaction_date columns to receipts table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("receipts", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "receipts", sa.Column("transaction_date", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("receipts", "transaction_date")
    op.drop_column("receipts", "notes")
