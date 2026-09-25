"""Track upload storage usage per global, college and user scope.

Revision ID: 0024_upload_quota_buckets
Revises: 0023_refresh_session_families
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_upload_quota_buckets"
down_revision: str | None = "0023_refresh_session_families"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_upload_quota_bucket",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_type", "scope_id", name="uk_v2_upload_quota_scope"),
    )
    op.execute(
        sa.text(
            "INSERT INTO v2_upload_quota_bucket (scope_type, scope_id, used_bytes) "
            "SELECT 'global', 0, COALESCE(SUM(size_bytes), 0) FROM v2_upload_asset"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO v2_upload_quota_bucket (scope_type, scope_id, used_bytes) "
            "SELECT 'college', college_id, SUM(size_bytes) FROM v2_upload_asset "
            "WHERE college_id IS NOT NULL GROUP BY college_id"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO v2_upload_quota_bucket (scope_type, scope_id, used_bytes) "
            "SELECT 'user', user_id, SUM(size_bytes) FROM v2_upload_asset GROUP BY user_id"
        )
    )


def downgrade() -> None:
    op.drop_table("v2_upload_quota_bucket")
