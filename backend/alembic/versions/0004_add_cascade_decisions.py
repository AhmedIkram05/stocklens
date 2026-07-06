"""Add cascade_decisions table for NLP cascade observability.

Stores per-receipt cascade outcomes: overall confidence, source,
discrepancies, and field confidences (JSONB).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source column to receipts table for cascade tracking
    op.add_column(
        "receipts",
        sa.Column("source", sa.String(20), nullable=True, server_default="regex"),
    )

    op.create_table(
        "cascade_decisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_text_hash", sa.String(16), nullable=False),
        sa.Column("regex_confidence", sa.REAL(), nullable=False),
        sa.Column("llm_confidence", sa.REAL(), nullable=True),
        sa.Column("chosen_source", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "chosen_source IN ('regex', 'cascade', 'pending_llm', 'degraded', 'failed')",
            name="chk_cascade_decisions_source",
        ),
        sa.Column("field_confidences", postgresql.JSONB(), nullable=True),
        sa.Column("discrepancies", postgresql.JSONB(), nullable=True),
        sa.Column("processing_time_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_cascade_decisions_receipt",
        "cascade_decisions",
        ["receipt_id"],
    )
    op.create_index(
        "idx_cascade_decisions_hash",
        "cascade_decisions",
        ["raw_text_hash"],
    )


def downgrade() -> None:
    op.drop_column("receipts", "source")
    op.drop_table("cascade_decisions")
