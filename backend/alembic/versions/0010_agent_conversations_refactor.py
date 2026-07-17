"""refactor agent_conversations into multi-turn schema

Creates a two-tier schema:
- conversations: lightweight metadata for the list endpoint
- agent_conversations: multi-turn message archive with conversation_id FK

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old index from old agent_conversations (af46e8a08234 created
    #    an idx_conversations_user on agent_conversations.user_id — must
    #    drop before we can reuse the name on our new conversations table).
    op.drop_index("idx_conversations_user", "agent_conversations")

    # 2. Create conversations table (lightweight metadata)
    op.create_table(
        "conversations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("idx_conversations_user", "conversations", ["user_id"])

    # 3. Drop old agent_conversations (zero rows — safe to recreate)
    op.drop_table("agent_conversations")

    # 4. Recreate as multi-turn archive
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_used", JSONB(), nullable=True),
        sa.Column("reasoning_steps", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("idx_agent_conversations_cid", "agent_conversations", ["conversation_id"])


def downgrade() -> None:
    # Reverse: drop new, restore old
    op.drop_index("idx_agent_conversations_cid", "agent_conversations")
    op.drop_table("agent_conversations")
    op.drop_index("idx_conversations_user", "conversations")
    op.drop_table("conversations")
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("tools_used", JSONB(), nullable=True),
        sa.Column("reasoning_steps", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("idx_conversations_user", "agent_conversations", ["user_id"])
