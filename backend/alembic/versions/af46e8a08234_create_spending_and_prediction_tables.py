"""create spending, prediction, drift, and agent tables

Revision ID: af46e8a08234
Revises:
Create Date: 2026-07-14 16:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af46e8a08234"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Spending categories
    op.create_table(
        "spending_categories",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column("merchant_keywords", JSONB()),
        sa.Column("associated_tickers", JSONB()),
    )

    # GIN index on merchant_keywords
    op.create_index(
        "idx_categories_keywords",
        "spending_categories",
        ["merchant_keywords"],
        postgresql_using="gin",
    )

    # Receipts (depends on spending_categories)
    op.create_table(
        "receipts",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(10, 2)),
        sa.Column("merchant_name", sa.String(255)),
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("spending_categories.id", ondelete="SET NULL"),
        ),
        sa.Column("ocr_raw_text", sa.Text()),
        sa.Column("ocr_confidence", sa.REAL()),
        sa.Column("line_items", JSONB()),
        sa.Column("receipt_image_s3_key", sa.String(500)),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_index("idx_receipts_user_date", "receipts", ["user_id", "scanned_at"])

    # Agent conversations
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text()),
        sa.Column("response", sa.Text()),
        sa.Column("tools_used", JSONB()),
        sa.Column("reasoning_steps", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("idx_conversations_user", "agent_conversations", ["user_id"])

    # Prediction log
    op.create_table(
        "prediction_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("prediction", sa.String(4), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities", JSONB()),
        sa.Column("features", JSONB()),
        sa.Column("feature_stats", JSONB()),
        sa.Column("raw_feature_names", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_index("idx_prediction_log_ticker_created", "prediction_log", ["ticker", "created_at"])
    op.create_index("idx_prediction_log_model_version", "prediction_log", ["model_version"])
    op.create_index("idx_prediction_log_created_at", "prediction_log", ["created_at"])

    # Drift metrics
    op.create_table(
        "drift_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("drift_run_id", sa.String(36), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("metric_type", sa.String(20), nullable=False),
        sa.Column("feature_name", sa.String(50), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("alert_triggered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reference_period", sa.String(30)),
        sa.Column("current_period", sa.String(30)),
        sa.Column("report_s3_key", sa.String(500)),
        sa.Column("details", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_index("idx_drift_metrics_run", "drift_metrics", ["drift_run_id"])
    op.create_index("idx_drift_metrics_ticker_metric", "drift_metrics", ["ticker", "metric_type"])
    op.create_index("idx_drift_metrics_alert", "drift_metrics", ["alert_triggered"])


def downgrade() -> None:
    op.drop_table("drift_metrics")
    op.drop_table("prediction_log")
    op.drop_table("agent_conversations")
    op.drop_table("receipts")
    op.drop_table("spending_categories")
