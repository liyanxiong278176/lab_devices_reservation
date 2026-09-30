"""Add scoped reservation rules and preventive maintenance records.

Revision ID: 0025_reservation_maintenance
Revises: 0024_upload_quota_buckets
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_reservation_maintenance"
down_revision: str | None = "0024_upload_quota_buckets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_reservation_rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("user_category", sa.String(length=20), server_default="ALL", nullable=False),
        sa.Column("max_booking_days", sa.Integer(), nullable=True),
        sa.Column("max_advance_days", sa.Integer(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "user_category",
            name="uk_v2_reservation_rule_scope_category",
        ),
    )
    # Preserve the existing device policy as a generic device-level rule.
    op.execute(
        sa.text(
            "INSERT INTO v2_reservation_rule "
            "(scope_type, scope_id, user_category, max_booking_days, max_advance_days, "
            "approval_required, created_at, updated_at) "
            "SELECT 'DEVICE', id, 'ALL', max_reservation_days, max_advance_days, "
            "need_approval, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM device"
        )
    )

    op.create_table(
        "v2_device_maintenance_plan",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("plan_type", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("interval_value", sa.Integer(), nullable=False),
        sa.Column("interval_unit", sa.String(length=12), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("downtime_start", sa.Date(), nullable=True),
        sa.Column("downtime_end", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("due_notice_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_maintenance_device_active",
        "v2_device_maintenance_plan",
        ["device_id", "active"],
    )
    op.create_index(
        "idx_v2_maintenance_due_active",
        "v2_device_maintenance_plan",
        ["active", "due_date", "plan_type"],
    )
    op.create_index(
        "idx_v2_maintenance_scope",
        "v2_device_maintenance_plan",
        ["college_id", "active", "id"],
    )

    op.create_table(
        "v2_device_maintenance_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("cycle_due_date", sa.Date(), nullable=False),
        sa.Column("completed_date", sa.Date(), nullable=False),
        sa.Column("downtime_start", sa.Date(), nullable=True),
        sa.Column("downtime_end", sa.Date(), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("performed_by", sa.BigInteger(), nullable=False),
        sa.Column("evidence_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("repair_report_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_asset_id"], ["v2_upload_asset.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["v2_device_maintenance_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["repair_report_id"], ["v2_repair_report.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "idempotency_key", name="uk_v2_maintenance_record_request"),
        sa.UniqueConstraint("plan_id", "cycle_due_date", name="uk_v2_maintenance_record_cycle"),
    )
    op.create_index(
        "idx_v2_maintenance_record_plan_date",
        "v2_device_maintenance_record",
        ["plan_id", "cycle_due_date", "id"],
    )
    op.create_index(
        "idx_v2_maintenance_record_device_date",
        "v2_device_maintenance_record",
        ["device_id", "completed_date", "id"],
    )
    op.create_index(
        "ix_v2_device_maintenance_record_college_id",
        "v2_device_maintenance_record",
        ["college_id"],
    )
    op.create_index(
        "ix_v2_device_maintenance_record_repair_report_id",
        "v2_device_maintenance_record",
        ["repair_report_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_device_maintenance_record_repair_report_id",
        table_name="v2_device_maintenance_record",
    )
    op.drop_index(
        "ix_v2_device_maintenance_record_college_id",
        table_name="v2_device_maintenance_record",
    )
    op.drop_index(
        "idx_v2_maintenance_record_device_date",
        table_name="v2_device_maintenance_record",
    )
    op.drop_index(
        "idx_v2_maintenance_record_plan_date",
        table_name="v2_device_maintenance_record",
    )
    op.drop_table("v2_device_maintenance_record")
    op.drop_index("idx_v2_maintenance_scope", table_name="v2_device_maintenance_plan")
    op.drop_index("idx_v2_maintenance_due_active", table_name="v2_device_maintenance_plan")
    op.drop_index("idx_v2_maintenance_device_active", table_name="v2_device_maintenance_plan")
    op.drop_table("v2_device_maintenance_plan")
    op.drop_table("v2_reservation_rule")
