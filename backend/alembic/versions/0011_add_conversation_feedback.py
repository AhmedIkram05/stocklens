"""add user_rating column to conversations table for thumbs feedback

Adds two columns to the conversations table so user feedback (thumbs up/down
+ optional comment) can be stored per-conversation even when no LangSmith
trace_id is available (e.g. historical conversations).

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("user_rating", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("user_rating_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "user_rating_comment")
    op.drop_column("conversations", "user_rating")
