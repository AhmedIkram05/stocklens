"""create spending categories, agent conversations, and extend receipts

Adds tables that were missing from the initial 0001-0008 chain:
spending_categories and agent_conversations.  Extends the receipts
table (created in 0001) with category_id and line_items.

prediction_log and drift_metrics are already created by 0005, so this
migration does not touch them.

Revision ID: af46e8a08234
Revises: 0008
Create Date: 2026-07-14 16:45:00.000000
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af46e8a08234"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Spending categories (new table)
    op.execute("""
        CREATE TABLE IF NOT EXISTS spending_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(50) UNIQUE NOT NULL,
            description VARCHAR(255),
            merchant_keywords JSONB,
            associated_tickers JSONB
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_categories_keywords
        ON spending_categories USING gin (merchant_keywords)
    """)

    # Receipts already exists from 0001 + 0002 — only add missing columns.
    op.execute("""
        ALTER TABLE receipts ADD COLUMN IF NOT EXISTS category_id UUID
        REFERENCES spending_categories(id) ON DELETE SET NULL
    """)
    op.execute("ALTER TABLE receipts ADD COLUMN IF NOT EXISTS line_items JSONB")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_receipts_user_date
        ON receipts (user_id, scanned_at)
    """)

    # Agent conversations (new table)
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_conversations (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message TEXT,
            response TEXT,
            tools_used JSONB,
            reasoning_steps JSONB,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_user
        ON agent_conversations (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_conversations")
    op.execute("DROP INDEX IF EXISTS idx_receipts_user_date")
    op.execute("ALTER TABLE receipts DROP COLUMN IF EXISTS line_items")
    op.execute("ALTER TABLE receipts DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS spending_categories")
