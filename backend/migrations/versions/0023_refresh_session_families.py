"""Bind access tokens to revocable refresh-session families.

Revision ID: 0023_refresh_session_families
Revises: 0022_ai_env_config
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_refresh_session_families"
down_revision: str | None = "0022_ai_env_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "v2_refresh_session",
        sa.Column("family_id", sa.String(length=64), nullable=True),
    )
    # Old access tokens are not bound to a server-side family. Revoke old
    # refresh sessions and require a fresh login instead of preserving tokens
    # that cannot be revoked on logout.
    op.execute(
        sa.text(
            "UPDATE v2_refresh_session "
            "SET family_id = token_id, revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)"
        )
    )
    with op.batch_alter_table("v2_refresh_session") as batch_op:
        batch_op.alter_column("family_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_index(
            "idx_v2_refresh_family_active",
            ["family_id", "revoked_at", "expires_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("v2_refresh_session") as batch_op:
        batch_op.drop_index("idx_v2_refresh_family_active")
        batch_op.drop_column("family_id")
