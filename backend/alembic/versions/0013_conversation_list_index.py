"""index conversations by user and updated_at

The history list sorts a user's conversations by updated_at before applying
LIMIT/OFFSET. The user-only index leaves that sort in memory.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_conversations_user_updated",
        "conversations",
        ["user_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_conversations_user_updated", table_name="conversations")
