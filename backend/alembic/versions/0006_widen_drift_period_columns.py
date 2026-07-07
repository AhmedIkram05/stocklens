"""Widen reference_period and current_period columns in drift_metrics.

The date-range format YYYY-MM-DD_YYYY-MM-DD is 21 characters, exceeding
the original VARCHAR(20). Widen to VARCHAR(30) to fit.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("drift_metrics", "reference_period", type_=sa.String(30))
    op.alter_column("drift_metrics", "current_period", type_=sa.String(30))


def downgrade() -> None:
    op.alter_column("drift_metrics", "reference_period", type_=sa.String(20))
    op.alter_column("drift_metrics", "current_period", type_=sa.String(20))
