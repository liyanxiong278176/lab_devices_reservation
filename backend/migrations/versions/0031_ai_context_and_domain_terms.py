"""Add L0 recall, protected-context snapshots, and reviewed domain terms.

Revision ID: 0031_ai_context_and_domain_terms
Revises: 0030_ai_runtime_memory_dlp
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_ai_context_and_domain_terms"
down_revision: str | None = "0030_ai_runtime_memory_dlp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_ai_message_recall",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("recalled_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["v2_ai_message.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "run_id", name="uk_v2_ai_message_recall_run"),
    )
    op.create_index("ix_v2_ai_message_recall_message_id", "v2_ai_message_recall", ["message_id"])
    op.create_index("ix_v2_ai_message_recall_run_id", "v2_ai_message_recall", ["run_id"])

    op.create_table(
        "v2_ai_context_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_message_ids", sa.JSON(), nullable=False),
        sa.Column("through_message_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["v2_ai_conversation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uk_v2_ai_context_conversation"),
    )
    op.create_index("ix_v2_ai_context_snapshot_user_id", "v2_ai_context_snapshot", ["user_id"])

    op.create_table(
        "v2_ai_domain_term",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("canonical", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=20), server_default="SYNONYM", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="APPROVED", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_v2_ai_domain_term_scope_status", "v2_ai_domain_term", ["college_id", "status"]
    )
    op.create_index("ix_v2_ai_domain_term_lookup", "v2_ai_domain_term", ["term", "status"])
    op.create_index("ix_v2_ai_domain_term_status", "v2_ai_domain_term", ["status"])
    op.create_index("ix_v2_ai_domain_term_created_by", "v2_ai_domain_term", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_v2_ai_domain_term_created_by", table_name="v2_ai_domain_term")
    op.drop_index("ix_v2_ai_domain_term_status", table_name="v2_ai_domain_term")
    op.drop_index("ix_v2_ai_domain_term_lookup", table_name="v2_ai_domain_term")
    op.drop_index("ix_v2_ai_domain_term_scope_status", table_name="v2_ai_domain_term")
    op.drop_table("v2_ai_domain_term")
    op.drop_index("ix_v2_ai_context_snapshot_user_id", table_name="v2_ai_context_snapshot")
    op.drop_table("v2_ai_context_snapshot")
    op.drop_index("ix_v2_ai_message_recall_run_id", table_name="v2_ai_message_recall")
    op.drop_index("ix_v2_ai_message_recall_message_id", table_name="v2_ai_message_recall")
    op.drop_table("v2_ai_message_recall")
