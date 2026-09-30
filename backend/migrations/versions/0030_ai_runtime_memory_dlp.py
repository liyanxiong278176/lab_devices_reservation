"""Add AI tool ledger, private memory lifecycle, DLP and citation confirmations.

Revision ID: 0030_ai_runtime_memory_dlp
Revises: 0029_cookie_auth_rbac
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_ai_runtime_memory_dlp"
down_revision: str | None = "0029_cookie_auth_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("v2_ai_message", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.add_column("v2_ai_message", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column(
        "v2_ai_message",
        sa.Column("recall_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("v2_ai_message", sa.Column("last_recalled_at", sa.DateTime(), nullable=True))
    op.create_index("ix_v2_ai_message_expires_at", "v2_ai_message", ["expires_at"])
    op.create_index("ix_v2_ai_message_archived_at", "v2_ai_message", ["archived_at"])
    op.execute(
        sa.text(
            "UPDATE v2_ai_message SET expires_at = DATE_ADD(created_at, INTERVAL 180 DAY) "
            "WHERE expires_at IS NULL"
        )
    )

    op.add_column("v2_ai_confirmation", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column("v2_ai_confirmation", sa.Column("arguments_hash", sa.String(64), nullable=True))
    op.add_column("v2_ai_confirmation", sa.Column("preview_hash", sa.String(64), nullable=True))
    op.create_index(
        "ix_v2_ai_confirmation_idempotency_key",
        "v2_ai_confirmation",
        ["idempotency_key"],
        unique=True,
    )

    op.create_table(
        "v2_ai_tool_execution",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("arguments_hash", sa.String(length=64), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="STARTED", nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("progress_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "idempotency_key", name="uk_v2_ai_tool_run_idempotency"),
    )
    op.create_index("ix_v2_ai_tool_execution_run_id", "v2_ai_tool_execution", ["run_id"])
    op.create_index("ix_v2_ai_tool_execution_user_id", "v2_ai_tool_execution", ["user_id"])
    op.create_index("ix_v2_ai_tool_execution_college_id", "v2_ai_tool_execution", ["college_id"])
    op.create_index(
        "ix_v2_ai_tool_run_status", "v2_ai_tool_execution", ["run_id", "status"]
    )

    op.create_table(
        "v2_ai_memory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("level", sa.String(length=2), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("source_run_ids", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING_CONFIRMATION",
            nullable=False,
        ),
        sa.Column("recall_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_recalled_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_v2_ai_memory_user_id", "v2_ai_memory", ["user_id"])
    op.create_index("ix_v2_ai_memory_college_id", "v2_ai_memory", ["college_id"])
    op.create_index("ix_v2_ai_memory_status", "v2_ai_memory", ["status"])
    op.create_index("ix_v2_ai_memory_expires_at", "v2_ai_memory", ["expires_at"])
    op.create_index(
        "ix_v2_ai_memory_owner_state", "v2_ai_memory", ["user_id", "status", "expires_at"]
    )
    op.create_index(
        "ix_v2_ai_memory_owner_level", "v2_ai_memory", ["user_id", "level", "scenario"]
    )

    op.create_table(
        "v2_ai_memory_recall",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("memory_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("used_in_response", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("recalled_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["v2_ai_memory.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id", "run_id", name="uk_v2_ai_memory_recall_run"),
    )
    op.create_index("ix_v2_ai_memory_recall_memory_id", "v2_ai_memory_recall", ["memory_id"])
    op.create_index("ix_v2_ai_memory_recall_run_id", "v2_ai_memory_recall", ["run_id"])
    op.create_index("idx_v2_ai_memory_recall_run", "v2_ai_memory_recall", ["run_id"])

    op.add_column("v2_knowledge_document", sa.Column("dlp_categories", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("v2_knowledge_document", "dlp_categories")
    op.drop_index("idx_v2_ai_memory_recall_run", table_name="v2_ai_memory_recall")
    op.drop_index("ix_v2_ai_memory_recall_run_id", table_name="v2_ai_memory_recall")
    op.drop_index("ix_v2_ai_memory_recall_memory_id", table_name="v2_ai_memory_recall")
    op.drop_table("v2_ai_memory_recall")
    op.drop_index("ix_v2_ai_memory_owner_level", table_name="v2_ai_memory")
    op.drop_index("ix_v2_ai_memory_owner_state", table_name="v2_ai_memory")
    op.drop_index("ix_v2_ai_memory_expires_at", table_name="v2_ai_memory")
    op.drop_index("ix_v2_ai_memory_status", table_name="v2_ai_memory")
    op.drop_index("ix_v2_ai_memory_college_id", table_name="v2_ai_memory")
    op.drop_index("ix_v2_ai_memory_user_id", table_name="v2_ai_memory")
    op.drop_table("v2_ai_memory")
    op.drop_index("ix_v2_ai_tool_run_status", table_name="v2_ai_tool_execution")
    op.drop_index("ix_v2_ai_tool_execution_college_id", table_name="v2_ai_tool_execution")
    op.drop_index("ix_v2_ai_tool_execution_user_id", table_name="v2_ai_tool_execution")
    op.drop_index("ix_v2_ai_tool_execution_run_id", table_name="v2_ai_tool_execution")
    op.drop_table("v2_ai_tool_execution")
    op.drop_index("ix_v2_ai_confirmation_idempotency_key", table_name="v2_ai_confirmation")
    op.drop_column("v2_ai_confirmation", "preview_hash")
    op.drop_column("v2_ai_confirmation", "arguments_hash")
    op.drop_column("v2_ai_confirmation", "idempotency_key")
    op.drop_index("ix_v2_ai_message_archived_at", table_name="v2_ai_message")
    op.drop_index("ix_v2_ai_message_expires_at", table_name="v2_ai_message")
    op.drop_column("v2_ai_message", "last_recalled_at")
    op.drop_column("v2_ai_message", "recall_count")
    op.drop_column("v2_ai_message", "archived_at")
    op.drop_column("v2_ai_message", "expires_at")
