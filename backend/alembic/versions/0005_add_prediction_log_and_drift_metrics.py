"""Add prediction_log and drift_metrics tables.

Stores every prediction request for drift monitoring and queryable
drift indicators per ticker per feature per drift run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- prediction_log ---
    op.create_table(
        "prediction_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("prediction", sa.String(4), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("probabilities", JSONB(), nullable=True),
        sa.Column("features", JSONB(), nullable=True),
        sa.Column("feature_stats", JSONB(), nullable=True),
        sa.Column("raw_feature_names", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_prediction_log_ticker_created",
        "prediction_log",
        ["ticker", "created_at"],
    )
    op.create_index(
        "idx_prediction_log_model_version",
        "prediction_log",
        ["model_version"],
    )
    op.create_index(
        "idx_prediction_log_created_at",
        "prediction_log",
        ["created_at"],
    )

    # --- drift_metrics ---
    op.create_table(
        "drift_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("drift_run_id", sa.String(36), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("metric_type", sa.String(20), nullable=False),
        sa.Column("feature_name", sa.String(50), nullable=False),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column(
            "alert_triggered",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("reference_period", sa.String(30), nullable=True),
        sa.Column("current_period", sa.String(30), nullable=True),
        sa.Column("report_s3_key", sa.String(500), nullable=True),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        "uq_drift_metrics_run_ticker_metric_feature",
        "drift_metrics",
        ["drift_run_id", "ticker", "metric_type", "feature_name"],
    )
    op.create_index("idx_drift_metrics_run", "drift_metrics", ["drift_run_id"])
    op.create_index(
        "idx_drift_metrics_ticker_metric",
        "drift_metrics",
        ["ticker", "metric_type"],
    )
    op.create_index(
        "idx_drift_metrics_alert",
        "drift_metrics",
        ["alert_triggered"],
    )


def downgrade() -> None:
    op.drop_table("drift_metrics")
    op.drop_table("prediction_log")
