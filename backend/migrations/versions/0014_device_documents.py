"""Add validated device manual and SOP attachments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_device_documents"
down_revision: str | None = "0013_reservation_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_device_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False, server_default="MANUAL"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["v2_upload_asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_device_document_device_active",
        "v2_device_document",
        ["device_id", "active", "created_at"],
    )
    op.create_index(
        "idx_v2_device_document_college_active",
        "v2_device_document",
        ["college_id", "active", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_v2_device_document_college_active",
        table_name="v2_device_document",
    )
    op.drop_index(
        "idx_v2_device_document_device_active",
        table_name="v2_device_document",
    )
    op.drop_table("v2_device_document")
