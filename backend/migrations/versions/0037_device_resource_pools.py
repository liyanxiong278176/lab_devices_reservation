"""Add logical resource pools for interchangeable physical devices.

Revision ID: 0037_device_resource_pools
Revises: 0036_knowledge_build_ordering
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_device_resource_pools"
down_revision: str | None = "0036_knowledge_build_ordering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_device_pool",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("lab_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["lab_id"], ["lab.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_device_pool_college_lab_id",
        "v2_device_pool",
        ["college_id", "lab_id", "id"],
    )
    op.add_column("device", sa.Column("pool_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_device_pool_id", "device", ["pool_id"])
    op.create_foreign_key("fk_device_pool_id", "device", "v2_device_pool", ["pool_id"], ["id"])

    # Keep all existing reservations attached to their original physical
    # device. Each historical device starts in its own one-item pool.
    op.execute(
        sa.text(
            "INSERT INTO v2_device_pool (id, name, college_id, lab_id, created_at, updated_at) "
            "SELECT id, name, college_id, lab_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM device"
        )
    )
    op.execute(sa.text("UPDATE device SET pool_id = id"))


def downgrade() -> None:
    op.drop_constraint("fk_device_pool_id", "device", type_="foreignkey")
    op.drop_index("ix_device_pool_id", table_name="device")
    op.drop_column("device", "pool_id")
    op.drop_index("idx_v2_device_pool_college_lab_id", table_name="v2_device_pool")
    op.drop_table("v2_device_pool")
