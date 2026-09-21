"""Store validated private attachments for non-AI business records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_private_upload_assets"
down_revision: str | None = "0011_non_ai_business_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_upload_asset",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("asset_token", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_token", name="uk_v2_upload_asset_token"),
    )
    op.create_index(
        "idx_v2_upload_asset_user_created",
        "v2_upload_asset",
        ["user_id", "created_at"],
    )
    op.create_index("idx_v2_upload_asset_college", "v2_upload_asset", ["college_id"])


def downgrade() -> None:
    op.drop_index("idx_v2_upload_asset_college", table_name="v2_upload_asset")
    op.drop_index("idx_v2_upload_asset_user_created", table_name="v2_upload_asset")
    op.drop_table("v2_upload_asset")
