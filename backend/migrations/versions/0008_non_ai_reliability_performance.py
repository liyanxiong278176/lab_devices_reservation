"""Add non-AI reliability fields and keyset/query indexes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_non_ai_perf"
down_revision: str | None = "0007_device_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "v2_outbox_task",
        sa.Column("aggregate_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "idx_v2_outbox_aggregate_status",
        "v2_outbox_task",
        ["aggregate_key", "status", "id"],
    )
    op.drop_index("idx_v2_outbox_status_execute", table_name="v2_outbox_task")
    op.create_index(
        "idx_v2_outbox_status_execute",
        "v2_outbox_task",
        ["status", "execute_at", "id"],
    )

    op.create_index("idx_reservation_user_id_v2", "reservation", ["user_id", "id"])
    op.create_index(
        "idx_reservation_college_status_id_v2",
        "reservation",
        ["college_id", "status", "id"],
    )
    op.create_index(
        "idx_device_college_status_id_v2",
        "device",
        ["college_id", "status", "id"],
    )
    op.create_index(
        "idx_device_college_lab_id_v2",
        "device",
        ["college_id", "lab_id", "id"],
    )
    op.create_index(
        "idx_notification_user_read_id_v2",
        "notification",
        ["user_id", "is_read", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_notification_user_read_id_v2", table_name="notification")
    op.drop_index("idx_device_college_lab_id_v2", table_name="device")
    op.drop_index("idx_device_college_status_id_v2", table_name="device")
    op.drop_index("idx_reservation_college_status_id_v2", table_name="reservation")
    op.drop_index("idx_reservation_user_id_v2", table_name="reservation")
    op.drop_index("idx_v2_outbox_status_execute", table_name="v2_outbox_task")
    op.create_index(
        "idx_v2_outbox_status_execute",
        "v2_outbox_task",
        ["status", "execute_at"],
    )
    op.drop_index("idx_v2_outbox_aggregate_status", table_name="v2_outbox_task")
    op.drop_column("v2_outbox_task", "aggregate_key")
