"""Add the post-use reservation feedback loop."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_reservation_feedback"
down_revision: str | None = "0012_private_upload_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_reservation_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", name="uk_v2_feedback_reservation"),
    )
    op.create_index(
        "idx_v2_feedback_device_created",
        "v2_reservation_feedback",
        ["device_id", "created_at"],
    )
    op.create_index(
        "idx_v2_feedback_college_created",
        "v2_reservation_feedback",
        ["college_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_feedback_college_created", table_name="v2_reservation_feedback")
    op.drop_index("idx_v2_feedback_device_created", table_name="v2_reservation_feedback")
    op.drop_table("v2_reservation_feedback")
