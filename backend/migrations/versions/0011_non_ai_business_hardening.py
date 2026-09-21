"""Complete the non-AI reservation operations and security model.

The migration keeps reservations at natural-day granularity.  Timestamps are
only audit fields; they are never used as booking slots.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_non_ai_business_hardening"
down_revision: str | None = "0010_reconcile_legacy_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("sys_user")}
    if "credit_score" not in user_columns:
        op.add_column(
            "sys_user",
            sa.Column("credit_score", sa.Integer(), nullable=False, server_default="100"),
        )
    if "booking_blocked_until" not in user_columns:
        op.add_column("sys_user", sa.Column("booking_blocked_until", sa.DateTime(), nullable=True))

    op.create_table(
        "v2_device_status_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("old_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_device_status_history_device_created",
        "v2_device_status_history",
        ["device_id", "created_at"],
    )
    op.create_index(
        "idx_v2_device_status_history_college",
        "v2_device_status_history",
        ["college_id"],
    )

    op.create_table(
        "v2_reservation_inspection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("condition", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("note", sa.String(1000), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", name="uk_v2_reservation_inspection_reservation"),
    )
    op.create_index(
        "idx_v2_reservation_inspection_device",
        "v2_reservation_inspection",
        ["device_id", "created_at"],
    )

    op.create_table(
        "v2_reservation_waitlist",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reservation_date", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="WAITING"),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "device_id",
            "reservation_date",
            "user_id",
            name="uk_v2_waitlist_device_date_user",
        ),
    )
    op.create_index(
        "idx_v2_waitlist_device_date_status",
        "v2_reservation_waitlist",
        ["device_id", "reservation_date", "status"],
    )
    op.create_index(
        "idx_v2_waitlist_user_created",
        "v2_reservation_waitlist",
        ["user_id", "created_at"],
    )

    op.create_table(
        "v2_reservation_blackout",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column("blocked_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "blocked_date", name="uk_v2_blackout_scope_date"
        ),
    )
    op.create_index(
        "idx_v2_blackout_scope_date",
        "v2_reservation_blackout",
        ["scope_type", "scope_id", "blocked_date"],
    )

    op.create_table(
        "v2_credit_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("reservation_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_credit_event_user_created",
        "v2_credit_event",
        ["user_id", "created_at"],
    )

    op.create_table(
        "v2_refresh_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by", sa.String(64), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id", name="uk_v2_refresh_token_id"),
    )
    op.create_index(
        "idx_v2_refresh_user_active",
        "v2_refresh_session",
        ["user_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "v2_audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_v2_audit_scope_created", "v2_audit_log", ["college_id", "created_at"])
    op.create_index(
        "idx_v2_audit_target_created",
        "v2_audit_log",
        ["target_type", "target_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_audit_target_created", table_name="v2_audit_log")
    op.drop_index("idx_v2_audit_scope_created", table_name="v2_audit_log")
    op.drop_table("v2_audit_log")
    op.drop_index("idx_v2_refresh_user_active", table_name="v2_refresh_session")
    op.drop_table("v2_refresh_session")
    op.drop_index("idx_v2_credit_event_user_created", table_name="v2_credit_event")
    op.drop_table("v2_credit_event")
    op.drop_index("idx_v2_blackout_scope_date", table_name="v2_reservation_blackout")
    op.drop_table("v2_reservation_blackout")
    op.drop_index("idx_v2_waitlist_user_created", table_name="v2_reservation_waitlist")
    op.drop_index("idx_v2_waitlist_device_date_status", table_name="v2_reservation_waitlist")
    op.drop_table("v2_reservation_waitlist")
    op.drop_index("idx_v2_reservation_inspection_device", table_name="v2_reservation_inspection")
    op.drop_table("v2_reservation_inspection")
    op.drop_index("idx_v2_device_status_history_college", table_name="v2_device_status_history")
    op.drop_index(
        "idx_v2_device_status_history_device_created",
        table_name="v2_device_status_history",
    )
    op.drop_table("v2_device_status_history")
    op.drop_column("sys_user", "booking_blocked_until")
    op.drop_column("sys_user", "credit_score")
