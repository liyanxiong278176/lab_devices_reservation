"""Add college-scoped penalty rules, appeals, credit accounts and overdue tracking.

Revision ID: 0038_penalties_overdue
Revises: 0037_device_resource_pools
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_penalties_overdue"
down_revision: str | None = "0037_device_resource_pools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_college_credit_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.Integer(), server_default="100", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "college_id", name="uk_v2_college_credit_user_college"),
    )
    op.create_index(
        "ix_v2_college_credit_account_user_id", "v2_college_credit_account", ["user_id"]
    )
    op.create_index(
        "ix_v2_college_credit_account_college_id", "v2_college_credit_account", ["college_id"]
    )
    op.create_index(
        "idx_v2_college_credit_college_points",
        "v2_college_credit_account",
        ["college_id", "points"],
    )
    op.execute(
        sa.text(
            "INSERT INTO v2_college_credit_account (user_id, college_id, points, updated_at) "
            "SELECT id, college_id, credit_score, CURRENT_TIMESTAMP FROM sys_user "
            "WHERE college_id IS NOT NULL"
        )
    )

    op.create_table(
        "v2_penalty_rule_version",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("grace_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tiers", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("college_id", "version", name="uk_v2_penalty_rule_college_version"),
    )
    op.create_index(
        "ix_v2_penalty_rule_version_college_id", "v2_penalty_rule_version", ["college_id"]
    )
    op.create_index(
        "ix_v2_penalty_rule_version_effective_at", "v2_penalty_rule_version", ["effective_at"]
    )
    op.create_index(
        "idx_v2_penalty_rule_effective",
        "v2_penalty_rule_version",
        ["college_id", "effective_at", "version"],
    )

    op.create_table(
        "v2_penalty_case",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("lab_id", sa.BigInteger(), nullable=True),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("violation_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("rule_version_id", sa.BigInteger(), nullable=True),
        sa.Column("occurrence_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("points_delta", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reservation_block_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["confirmed_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["lab_id"], ["lab.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"]),
        sa.ForeignKeyConstraint(["rule_version_id"], ["v2_penalty_rule_version.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reservation_id", "violation_type", name="uk_v2_penalty_reservation_type"
        ),
    )
    op.create_index("ix_v2_penalty_case_reservation_id", "v2_penalty_case", ["reservation_id"])
    op.create_index("ix_v2_penalty_case_user_id", "v2_penalty_case", ["user_id"])
    op.create_index("ix_v2_penalty_case_college_id", "v2_penalty_case", ["college_id"])
    op.create_index("ix_v2_penalty_case_lab_id", "v2_penalty_case", ["lab_id"])
    op.create_index("ix_v2_penalty_case_device_id", "v2_penalty_case", ["device_id"])
    op.create_index("ix_v2_penalty_case_event_at", "v2_penalty_case", ["event_at"])
    op.create_index("ix_v2_penalty_case_status", "v2_penalty_case", ["status"])
    op.create_index(
        "idx_v2_penalty_user_college_event",
        "v2_penalty_case",
        ["user_id", "college_id", "event_at"],
    )
    op.create_index(
        "idx_v2_penalty_college_status",
        "v2_penalty_case",
        ["college_id", "status", "applied_at"],
    )

    op.create_table(
        "v2_reservation_overdue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reservation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("lab_id", sa.BigInteger(), nullable=True),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("grace_deadline_at", sa.DateTime(), nullable=False),
        sa.Column("rule_version_id", sa.BigInteger(), nullable=True),
        sa.Column("penalty_case_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="GRACE", nullable=False),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("escalated_by", sa.BigInteger(), nullable=True),
        sa.Column("escalation_reason", sa.String(length=1000), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["escalated_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["lab_id"], ["lab.id"]),
        sa.ForeignKeyConstraint(["penalty_case_id"], ["v2_penalty_case.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservation.id"]),
        sa.ForeignKeyConstraint(["rule_version_id"], ["v2_penalty_rule_version.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id", name="uk_v2_reservation_overdue_reservation"),
    )
    op.create_index(
        "ix_v2_reservation_overdue_reservation_id", "v2_reservation_overdue", ["reservation_id"]
    )
    op.create_index("ix_v2_reservation_overdue_user_id", "v2_reservation_overdue", ["user_id"])
    op.create_index(
        "ix_v2_reservation_overdue_college_id", "v2_reservation_overdue", ["college_id"]
    )
    op.create_index("ix_v2_reservation_overdue_lab_id", "v2_reservation_overdue", ["lab_id"])
    op.create_index("ix_v2_reservation_overdue_device_id", "v2_reservation_overdue", ["device_id"])
    op.create_index(
        "ix_v2_reservation_overdue_grace_deadline_at",
        "v2_reservation_overdue",
        ["grace_deadline_at"],
    )
    op.create_index("ix_v2_reservation_overdue_status", "v2_reservation_overdue", ["status"])
    op.create_index(
        "idx_v2_reservation_overdue_scope_status",
        "v2_reservation_overdue",
        ["college_id", "status", "grace_deadline_at"],
    )
    op.create_index(
        "idx_v2_reservation_overdue_user_status",
        "v2_reservation_overdue",
        ["user_id", "status"],
    )

    op.create_table(
        "v2_reservation_overdue_followup",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("overdue_id", sa.BigInteger(), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=False),
        sa.Column("contacted_at", sa.DateTime(), nullable=False),
        sa.Column("result", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["overdue_id"], ["v2_reservation_overdue.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_v2_reservation_overdue_followup_overdue_id",
        "v2_reservation_overdue_followup",
        ["overdue_id"],
    )
    op.create_index(
        "ix_v2_reservation_overdue_followup_operator_id",
        "v2_reservation_overdue_followup",
        ["operator_id"],
    )
    op.create_index(
        "idx_v2_overdue_followup_case_time",
        "v2_reservation_overdue_followup",
        ["overdue_id", "contacted_at"],
    )

    op.create_table(
        "v2_reservation_booking_restriction",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("penalty_case_id", sa.BigInteger(), nullable=True),
        sa.Column("overdue_id", sa.BigInteger(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("release_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["overdue_id"], ["v2_reservation_overdue.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["penalty_case_id"], ["v2_penalty_case.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("penalty_case_id", name="uk_v2_booking_restriction_penalty"),
        sa.UniqueConstraint("overdue_id", name="uk_v2_booking_restriction_overdue"),
    )
    op.create_index(
        "ix_v2_reservation_booking_restriction_user_id",
        "v2_reservation_booking_restriction",
        ["user_id"],
    )
    op.create_index(
        "ix_v2_reservation_booking_restriction_college_id",
        "v2_reservation_booking_restriction",
        ["college_id"],
    )
    op.create_index(
        "ix_v2_reservation_booking_restriction_ends_at",
        "v2_reservation_booking_restriction",
        ["ends_at"],
    )
    op.create_index(
        "idx_v2_booking_restriction_user_scope",
        "v2_reservation_booking_restriction",
        ["user_id", "college_id", "scope_type", "scope_id", "ends_at"],
    )

    op.create_table(
        "v2_penalty_appeal",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("penalty_case_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("evidence", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("reviewer_id", sa.BigInteger(), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("result_reason", sa.String(length=2000), nullable=True),
        sa.Column("adjusted_points_delta", sa.Integer(), nullable=True),
        sa.Column("adjusted_block_days", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.ForeignKeyConstraint(["penalty_case_id"], ["v2_penalty_case.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "penalty_case_id", "attempt_number", name="uk_v2_penalty_appeal_attempt"
        ),
    )
    op.create_index(
        "ix_v2_penalty_appeal_penalty_case_id", "v2_penalty_appeal", ["penalty_case_id"]
    )
    op.create_index("ix_v2_penalty_appeal_user_id", "v2_penalty_appeal", ["user_id"])
    op.create_index("ix_v2_penalty_appeal_college_id", "v2_penalty_appeal", ["college_id"])
    op.create_index("ix_v2_penalty_appeal_status", "v2_penalty_appeal", ["status"])
    op.create_index(
        "idx_v2_penalty_appeal_college_status",
        "v2_penalty_appeal",
        ["college_id", "status", "submitted_at"],
    )
    op.create_index("idx_v2_penalty_appeal_user", "v2_penalty_appeal", ["user_id", "submitted_at"])

    op.create_table(
        "v2_penalty_grace_bounds",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("minimum_days", sa.Integer(), nullable=False),
        sa.Column("maximum_days", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO v2_penalty_grace_bounds "
            "(id, minimum_days, maximum_days, updated_at) VALUES (1, 0, 30, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("v2_penalty_grace_bounds")
    op.drop_index("idx_v2_penalty_appeal_user", table_name="v2_penalty_appeal")
    op.drop_index("idx_v2_penalty_appeal_college_status", table_name="v2_penalty_appeal")
    op.drop_index("ix_v2_penalty_appeal_status", table_name="v2_penalty_appeal")
    op.drop_index("ix_v2_penalty_appeal_college_id", table_name="v2_penalty_appeal")
    op.drop_index("ix_v2_penalty_appeal_user_id", table_name="v2_penalty_appeal")
    op.drop_index("ix_v2_penalty_appeal_penalty_case_id", table_name="v2_penalty_appeal")
    op.drop_table("v2_penalty_appeal")
    op.drop_index(
        "idx_v2_booking_restriction_user_scope", table_name="v2_reservation_booking_restriction"
    )
    op.drop_index(
        "ix_v2_reservation_booking_restriction_ends_at",
        table_name="v2_reservation_booking_restriction",
    )
    op.drop_index(
        "ix_v2_reservation_booking_restriction_college_id",
        table_name="v2_reservation_booking_restriction",
    )
    op.drop_index(
        "ix_v2_reservation_booking_restriction_user_id",
        table_name="v2_reservation_booking_restriction",
    )
    op.drop_table("v2_reservation_booking_restriction")
    op.drop_index("idx_v2_overdue_followup_case_time", table_name="v2_reservation_overdue_followup")
    op.drop_index(
        "ix_v2_reservation_overdue_followup_operator_id",
        table_name="v2_reservation_overdue_followup",
    )
    op.drop_index(
        "ix_v2_reservation_overdue_followup_overdue_id",
        table_name="v2_reservation_overdue_followup",
    )
    op.drop_table("v2_reservation_overdue_followup")
    op.drop_index("idx_v2_reservation_overdue_user_status", table_name="v2_reservation_overdue")
    op.drop_index("idx_v2_reservation_overdue_scope_status", table_name="v2_reservation_overdue")
    op.drop_index("ix_v2_reservation_overdue_status", table_name="v2_reservation_overdue")
    op.drop_index(
        "ix_v2_reservation_overdue_grace_deadline_at", table_name="v2_reservation_overdue"
    )
    op.drop_index("ix_v2_reservation_overdue_device_id", table_name="v2_reservation_overdue")
    op.drop_index("ix_v2_reservation_overdue_lab_id", table_name="v2_reservation_overdue")
    op.drop_index("ix_v2_reservation_overdue_college_id", table_name="v2_reservation_overdue")
    op.drop_index("ix_v2_reservation_overdue_user_id", table_name="v2_reservation_overdue")
    op.drop_index("ix_v2_reservation_overdue_reservation_id", table_name="v2_reservation_overdue")
    op.drop_table("v2_reservation_overdue")
    op.drop_index("idx_v2_penalty_college_status", table_name="v2_penalty_case")
    op.drop_index("idx_v2_penalty_user_college_event", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_status", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_event_at", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_device_id", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_lab_id", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_college_id", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_user_id", table_name="v2_penalty_case")
    op.drop_index("ix_v2_penalty_case_reservation_id", table_name="v2_penalty_case")
    op.drop_table("v2_penalty_case")
    op.drop_index("idx_v2_penalty_rule_effective", table_name="v2_penalty_rule_version")
    op.drop_index("ix_v2_penalty_rule_version_effective_at", table_name="v2_penalty_rule_version")
    op.drop_index("ix_v2_penalty_rule_version_college_id", table_name="v2_penalty_rule_version")
    op.drop_table("v2_penalty_rule_version")
    op.drop_index("idx_v2_college_credit_college_points", table_name="v2_college_credit_account")
    op.drop_index("ix_v2_college_credit_account_college_id", table_name="v2_college_credit_account")
    op.drop_index("ix_v2_college_credit_account_user_id", table_name="v2_college_credit_account")
    op.drop_table("v2_college_credit_account")
