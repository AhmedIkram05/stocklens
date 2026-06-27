"""initial_schema

Create all 10 tables, 9 indexes, the ``update_updated_at_column()`` trigger
function, and 3 row-level triggers.

Revision ID: 0001
Revises:
Create Date: 2026-06-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Trigger function ────────────────────────────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── Users ───────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        """
        CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """
    )

    # ── Refresh tokens ──────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # ── Portfolios ──────────────────────────────────────────────────────────
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(100)),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        """
        CREATE TRIGGER trg_portfolios_updated_at BEFORE UPDATE ON portfolios
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """
    )

    # ── Holdings ────────────────────────────────────────────────────────────
    op.create_table(
        "holdings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("shares", sa.Numeric(18, 6), nullable=False),
        sa.Column("average_cost_basis", sa.Numeric(12, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        """
        CREATE TRIGGER trg_holdings_updated_at BEFORE UPDATE ON holdings
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """
    )

    # ── Transactions ────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("type", sa.String(4), nullable=False),
        sa.Column("shares", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_per_share", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type IN ('BUY', 'SELL')",
                           name="chk_transactions_type"),
        sa.CheckConstraint(
            "total_amount = shares * price_per_share",
            name="chk_transactions_amount",
        ),
    )

    # ── Spending categories ─────────────────────────────────────────────────
    op.create_table(
        "spending_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("merchant_keywords", postgresql.JSONB()),
        sa.Column("associated_tickers", postgresql.JSONB()),
    )

    # ── Receipts ────────────────────────────────────────────────────────────
    op.create_table(
        "receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2)),
        sa.Column("merchant_name", sa.String(255)),
        sa.Column("category_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("spending_categories.id",
                                ondelete="SET NULL")),
        sa.Column("ocr_raw_text", sa.Text()),
        sa.Column("ocr_confidence", sa.REAL()),
        sa.Column("line_items", postgresql.JSONB()),
        sa.Column("receipt_image_s3_key", sa.String(500)),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # ── OHLCV prices ────────────────────────────────────────────────────────
    op.create_table(
        "ohlcv_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4)),
        sa.Column("high", sa.Numeric(12, 4)),
        sa.Column("low", sa.Numeric(12, 4)),
        sa.Column("close", sa.Numeric(12, 4)),
        sa.Column("adjusted_close", sa.Numeric(12, 4)),
        sa.Column("volume", sa.BigInteger()),
    )

    # ── Model registry ──────────────────────────────────────────────────────
    op.create_table(
        "model_registry",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("ticker", sa.String(10)),
        sa.Column("mlflow_run_id", sa.String(100)),
        sa.Column("model_version", sa.String(20)),
        sa.Column("alias", sa.String(20)),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("trained_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    # ── Agent conversations ─────────────────────────────────────────────────
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("response", sa.Text()),
        sa.Column("tools_used", postgresql.JSONB()),
        sa.Column("reasoning_steps", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )

    # ── Indexes ─────────────────────────────────────────────────────────────
    op.create_index("idx_portfolios_user_id", "portfolios", ["user_id"])
    op.create_index(
        "idx_holdings_portfolio_ticker", "holdings",
        ["portfolio_id", "ticker"], unique=True,
    )
    op.create_index(
        "idx_transactions_portfolio_date", "transactions",
        ["portfolio_id", "transaction_date"],
    )
    op.create_index(
        "idx_receipts_user_date", "receipts",
        ["user_id", "scanned_at"],
    )
    op.create_index(
        "idx_ohlcv_ticker_date", "ohlcv_prices",
        ["ticker", "date"], unique=True,
    )
    op.create_index("idx_refresh_tokens_user", "refresh_tokens", ["user_id"])
    op.create_index(
        "idx_refresh_tokens_hash", "refresh_tokens",
        ["token_hash"], unique=True,
    )
    op.create_index(
        "idx_categories_keywords", "spending_categories",
        ["merchant_keywords"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_conversations_user", "agent_conversations",
        ["user_id"],
    )


def downgrade() -> None:
    # Drop triggers first (before their tables)
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users")
    op.execute("DROP TRIGGER IF EXISTS trg_portfolios_updated_at ON portfolios")
    op.execute("DROP TRIGGER IF EXISTS trg_holdings_updated_at ON holdings")

    # Drop tables in reverse dependency order
    op.drop_table("agent_conversations")
    op.drop_table("model_registry")
    op.drop_table("ohlcv_prices")
    op.drop_table("receipts")
    op.drop_table("spending_categories")
    op.drop_table("transactions")
    op.drop_table("holdings")
    op.drop_table("portfolios")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

    # Remove the trigger function
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
