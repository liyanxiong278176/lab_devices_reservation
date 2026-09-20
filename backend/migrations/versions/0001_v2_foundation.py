"""Add FastAPI v2 tenant, date reservation and durable task foundations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_v2_foundation"
down_revision: str | None = "0000_legacy_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "college",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("idx_college_manager_id_v2", "college", ["manager_id"])

    op.add_column("sys_user", sa.Column("college_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_sys_user_college_id_v2", "sys_user", ["college_id"])
    op.create_foreign_key(
        "fk_sys_user_college_v2",
        "sys_user",
        "college",
        ["college_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_college_manager_v2",
        "college",
        "sys_user",
        ["manager_id"],
        ["id"],
    )

    op.add_column("lab", sa.Column("college_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_lab_college_id_v2", "lab", ["college_id"])
    op.create_foreign_key("fk_lab_college_v2", "lab", "college", ["college_id"], ["id"])

    op.add_column("device", sa.Column("college_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_device_college_id_v2", "device", ["college_id"])
    op.create_foreign_key("fk_device_college_v2", "device", "college", ["college_id"], ["id"])

    op.add_column("reservation", sa.Column("college_id", sa.BigInteger(), nullable=True))
    op.add_column("reservation", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("reservation", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("reservation", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_index("idx_reservation_college_v2", "reservation", ["college_id"])
    op.create_index("idx_reservation_batch_v2", "reservation", ["batch_id"])
    op.create_index("idx_reservation_dates_v2", "reservation", ["start_date", "end_date"])

    op.add_column("notification", sa.Column("college_id", sa.BigInteger(), nullable=True))
    op.create_index("idx_notification_college_v2", "notification", ["college_id"])

    op.execute(
        "UPDATE reservation SET start_date = DATE(start_time), "
        "end_date = DATE(end_time) WHERE start_date IS NULL AND start_time IS NOT NULL"
    )
    op.execute(
        "UPDATE reservation r JOIN device d ON d.id = r.device_id "
        "SET r.college_id = d.college_id WHERE r.college_id IS NULL"
    )
    op.execute(
        "UPDATE device d JOIN lab l ON l.id = d.lab_id "
        "SET d.college_id = l.college_id WHERE d.college_id IS NULL"
    )

    op.create_table(
        "v2_reservation_day",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "date", name="uk_v2_device_date"),
    )
    op.create_index(
        "idx_v2_reservation_day_device_date",
        "v2_reservation_day",
        ["device_id", "date"],
    )

    op.create_table(
        "v2_outbox_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_key", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("execute_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_key", name="uk_v2_outbox_task_key"),
    )
    op.create_index(
        "idx_v2_outbox_status_execute",
        "v2_outbox_task",
        ["status", "execute_at"],
    )

    op.create_table(
        "v2_idempotency_key",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
        sa.Column("response_code", sa.String(length=32), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uk_v2_idempotency_user_key"),
    )


def downgrade() -> None:
    op.drop_table("v2_idempotency_key")
    op.drop_index("idx_v2_outbox_status_execute", table_name="v2_outbox_task")
    op.drop_table("v2_outbox_task")
    op.drop_index("idx_v2_reservation_day_device_date", table_name="v2_reservation_day")
    op.drop_table("v2_reservation_day")
    op.drop_index("idx_notification_college_v2", table_name="notification")
    op.drop_column("notification", "college_id")
    op.drop_index("idx_reservation_dates_v2", table_name="reservation")
    op.drop_index("idx_reservation_batch_v2", table_name="reservation")
    op.drop_index("idx_reservation_college_v2", table_name="reservation")
    op.drop_column("reservation", "batch_id")
    op.drop_column("reservation", "end_date")
    op.drop_column("reservation", "start_date")
    op.drop_column("reservation", "college_id")
    op.drop_constraint("fk_device_college_v2", "device", type_="foreignkey")
    op.drop_index("idx_device_college_id_v2", table_name="device")
    op.drop_column("device", "college_id")
    op.drop_constraint("fk_lab_college_v2", "lab", type_="foreignkey")
    op.drop_index("idx_lab_college_id_v2", table_name="lab")
    op.drop_column("lab", "college_id")
    op.drop_constraint("fk_sys_user_college_v2", "sys_user", type_="foreignkey")
    op.drop_index("idx_sys_user_college_id_v2", table_name="sys_user")
    op.drop_column("sys_user", "college_id")
    op.drop_constraint("fk_college_manager_v2", "college", type_="foreignkey")
    op.drop_index("idx_college_manager_id_v2", table_name="college")
    op.drop_table("college")
