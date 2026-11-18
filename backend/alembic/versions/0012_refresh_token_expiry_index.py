"""index refresh_tokens.expires_at for retention cleanup

Rotation inserts a row per refresh and only flips ``revoked``. The cleanup in
the auth paths deletes rows older than one day past expiry; this index keeps
that delete and any future purge from scanning the table.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_refresh_tokens_expires_at",
        "refresh_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_refresh_tokens_expires_at", table_name="refresh_tokens")
