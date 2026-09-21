"""Add operational controls for asset custody, safety access and reporting.

All additions are nullable/defaulted so existing v2 data remains readable while
the application gradually backfills asset metadata and document versions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_non_ai_operations"
down_revision: str | None = "0014_device_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add("device", sa.Column("asset_code", sa.String(80), nullable=True))
    _add("device", sa.Column("serial_number", sa.String(120), nullable=True))
    _add("device", sa.Column("purchase_date", sa.Date(), nullable=True))
    _add("device", sa.Column("warranty_until", sa.Date(), nullable=True))
    _add(
        "device",
        sa.Column("allow_external_loan", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add(
        "device",
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="STANDARD"),
    )
    _add(
        "device",
        sa.Column("requires_safety_ack", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add(
        "device",
        sa.Column(
            "requires_qualification",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add("device", sa.Column("max_advance_days", sa.Integer(), nullable=True))
    _add("device", sa.Column("qr_token", sa.String(96), nullable=True))
    inspector = sa.inspect(op.get_bind())
    device_indexes = {item["name"] for item in inspector.get_indexes("device")}
    if "ix_device_asset_code" not in device_indexes:
        op.create_index("ix_device_asset_code", "device", ["asset_code"], unique=True)
    if "ix_device_qr_token" not in device_indexes:
        op.create_index("ix_device_qr_token", "device", ["qr_token"], unique=True)

    _add(
        "reservation",
        sa.Column("handover_status", sa.String(24), nullable=False, server_default="NOT_REQUIRED"),
    )
    _add("reservation", sa.Column("safety_acknowledged_at", sa.DateTime(), nullable=True))
    _add("reservation", sa.Column("safety_document_version", sa.String(40), nullable=True))

    _add(
        "v2_device_document",
        sa.Column("version", sa.String(40), nullable=False, server_default="1.0"),
    )
    _add(
        "v2_device_document",
        sa.Column("requires_ack", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add("v2_device_document", sa.Column("published_at", sa.DateTime(), nullable=True))

    _add(
        "v2_repair_report",
        sa.Column("priority", sa.String(20), nullable=False, server_default="NORMAL"),
    )
    _add("v2_repair_report", sa.Column("response_due_at", sa.DateTime(), nullable=True))
    _add("v2_repair_report", sa.Column("resolve_due_at", sa.DateTime(), nullable=True))
    _add("v2_repair_report", sa.Column("user_confirmed_at", sa.DateTime(), nullable=True))
    _add("v2_repair_report", sa.Column("user_confirmation_note", sa.String(500), nullable=True))
    _add("v2_repair_report", sa.Column("closed_at", sa.DateTime(), nullable=True))
    repair_indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("v2_repair_report")
    }
    if "ix_v2_repair_report_priority" not in repair_indexes:
        op.create_index("ix_v2_repair_report_priority", "v2_repair_report", ["priority"])

    op.create_table(
        "v2_device_document_ack",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("reservation_id", sa.BigInteger(), nullable=True),
        sa.Column("document_version", sa.String(40), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["v2_device_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "user_id", name="uk_v2_device_document_ack_user"),
    )
    op.create_index(
        "idx_v2_device_document_ack_user",
        "v2_device_document_ack",
        ["user_id", "acknowledged_at"],
    )

    op.create_table(
        "v2_device_qualification",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("qualification_type", sa.String(80), nullable=False, server_default="TRAINING"),
        sa.Column("asset_id", sa.BigInteger(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["v2_upload_asset.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "user_id", name="uk_v2_device_qualification_user"),
    )
    op.create_index(
        "idx_v2_device_qualification_scope_status",
        "v2_device_qualification",
        ["college_id", "status", "valid_until"],
    )
    op.create_index(
        "idx_v2_device_qualification_user_status",
        "v2_device_qualification",
        ["user_id", "status", "valid_until"],
    )

    op.create_table(
        "v2_device_handover",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("handover_by", sa.BigInteger(), nullable=True),
        sa.Column("handover_at", sa.DateTime(), nullable=True),
        sa.Column("handover_condition", sa.String(20), nullable=True),
        sa.Column("handover_note", sa.String(1000), nullable=True),
        sa.Column("returned_by", sa.BigInteger(), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("return_condition", sa.String(20), nullable=True),
        sa.Column("return_note", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["handover_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["returned_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", name="uk_v2_device_handover_reservation"),
    )
    op.create_index(
        "idx_v2_device_handover_device_status",
        "v2_device_handover",
        ["device_id", "status", "created_at"],
    )
    op.create_index(
        "idx_v2_device_handover_scope_status",
        "v2_device_handover",
        ["college_id", "status"],
    )

    op.create_table(
        "v2_repair_worklog",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("content", sa.String(2000), nullable=False),
        sa.Column("image_urls", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["report_id"], ["v2_repair_report.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_repair_worklog_report_created",
        "v2_repair_worklog",
        ["report_id", "created_at"],
    )

    op.create_table(
        "v2_export_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("requester_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("export_type", sa.String(40), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("file_token", sa.String(96), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["requester_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_token", name="uk_v2_export_task_file_token"),
    )
    op.create_index(
        "idx_v2_export_task_user_status_created",
        "v2_export_task",
        ["requester_id", "status", "created_at"],
    )
    op.create_index(
        "idx_v2_export_task_status_created",
        "v2_export_task",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_export_task_status_created", table_name="v2_export_task")
    op.drop_index("idx_v2_export_task_user_status_created", table_name="v2_export_task")
    op.drop_table("v2_export_task")
    op.drop_index("idx_v2_repair_worklog_report_created", table_name="v2_repair_worklog")
    op.drop_table("v2_repair_worklog")
    op.drop_index("idx_v2_device_handover_scope_status", table_name="v2_device_handover")
    op.drop_index("idx_v2_device_handover_device_status", table_name="v2_device_handover")
    op.drop_table("v2_device_handover")
    op.drop_index(
        "idx_v2_device_qualification_user_status",
        table_name="v2_device_qualification",
    )
    op.drop_index(
        "idx_v2_device_qualification_scope_status",
        table_name="v2_device_qualification",
    )
    op.drop_table("v2_device_qualification")
    op.drop_index("idx_v2_device_document_ack_user", table_name="v2_device_document_ack")
    op.drop_table("v2_device_document_ack")
    op.drop_index("ix_v2_repair_report_priority", table_name="v2_repair_report")
    for column in (
        "closed_at",
        "user_confirmation_note",
        "user_confirmed_at",
        "resolve_due_at",
        "response_due_at",
        "priority",
    ):
        op.drop_column("v2_repair_report", column)
    for column in ("published_at", "requires_ack", "version"):
        op.drop_column("v2_device_document", column)
    for column in ("safety_document_version", "safety_acknowledged_at", "handover_status"):
        op.drop_column("reservation", column)
    for column in (
        "qr_token",
        "max_advance_days",
        "requires_qualification",
        "requires_safety_ack",
        "risk_level",
        "allow_external_loan",
        "warranty_until",
        "purchase_date",
        "serial_number",
        "asset_code",
    ):
        op.drop_column("device", column)
