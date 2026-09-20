"""Add tenant-scoped repair tickets for the practical operations workflow."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_repairs"
down_revision: str | None = "0002_ai_agent_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_repair_report",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_urls", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("handler_id", sa.BigInteger(), nullable=True),
        sa.Column("resolution_note", sa.String(length=1000), nullable=True),
        sa.Column("taken_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["reporter_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["handler_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_repair_scope_status",
        "v2_repair_report",
        ["college_id", "status", "created_at"],
    )
    op.create_index(
        "idx_v2_repair_reporter",
        "v2_repair_report",
        ["reporter_id", "created_at"],
    )
    op.create_index(
        "idx_v2_repair_device_status",
        "v2_repair_report",
        ["device_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_repair_device_status", table_name="v2_repair_report")
    op.drop_index("idx_v2_repair_reporter", table_name="v2_repair_report")
    op.drop_index("idx_v2_repair_scope_status", table_name="v2_repair_report")
    op.drop_table("v2_repair_report")
