"""Persist the Agent Harness, human confirmation and tenant-aware knowledge base."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_agent_rag"
down_revision: str | None = "0001_v2_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "v2_ai_provider_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_key", sa.String(80), nullable=False, server_default="global"),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("daily_quota", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", name="uk_v2_ai_provider_scope"),
    )
    op.create_index("idx_v2_ai_provider_college", "v2_ai_provider_config", ["college_id"])

    op.create_table(
        "v2_ai_conversation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default="新对话"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("graph_thread_id", sa.String(80), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_thread_id"),
    )
    op.create_index(
        "idx_v2_ai_conversation_user_updated", "v2_ai_conversation", ["user_id", "updated_at"]
    )
    op.create_index("idx_v2_ai_conversation_college", "v2_ai_conversation", ["college_id"])

    op.create_table(
        "v2_ai_message",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["v2_ai_conversation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_ai_message_conversation_created", "v2_ai_message", ["conversation_id", "created_at"]
    )

    op.create_table(
        "v2_ai_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_key", sa.String(100), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="RUNNING"),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=True),
        sa.Column("citations_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["v2_ai_conversation.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key", name="uk_v2_ai_run_key"),
    )
    op.create_index("idx_v2_ai_run_conversation", "v2_ai_run", ["conversation_id", "created_at"])
    op.create_index("idx_v2_ai_run_user", "v2_ai_run", ["user_id"])

    op.create_table(
        "v2_ai_confirmation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["v2_ai_conversation.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_ai_confirmation_user_status", "v2_ai_confirmation", ["user_id", "status"]
    )

    op.create_table(
        "v2_knowledge_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="FAQ"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_v2_knowledge_scope_status", "v2_knowledge_document", ["college_id", "status"]
    )

    op.create_table(
        "v2_knowledge_chunk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("point_id", sa.String(100), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["v2_knowledge_document.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uk_v2_knowledge_chunk_order"),
        sa.UniqueConstraint("point_id", name="uk_v2_knowledge_chunk_point"),
    )
    op.create_index("idx_v2_knowledge_chunk_document", "v2_knowledge_chunk", ["document_id"])
    op.create_index("idx_v2_knowledge_chunk_college", "v2_knowledge_chunk", ["college_id"])


def downgrade() -> None:
    op.drop_index("idx_v2_knowledge_chunk_college", table_name="v2_knowledge_chunk")
    op.drop_index("idx_v2_knowledge_chunk_document", table_name="v2_knowledge_chunk")
    op.drop_table("v2_knowledge_chunk")
    op.drop_index("idx_v2_knowledge_scope_status", table_name="v2_knowledge_document")
    op.drop_table("v2_knowledge_document")
    op.drop_index("idx_v2_ai_confirmation_user_status", table_name="v2_ai_confirmation")
    op.drop_table("v2_ai_confirmation")
    op.drop_index("idx_v2_ai_run_user", table_name="v2_ai_run")
    op.drop_index("idx_v2_ai_run_conversation", table_name="v2_ai_run")
    op.drop_table("v2_ai_run")
    op.drop_index("idx_v2_ai_message_conversation_created", table_name="v2_ai_message")
    op.drop_table("v2_ai_message")
    op.drop_index("idx_v2_ai_conversation_college", table_name="v2_ai_conversation")
    op.drop_index("idx_v2_ai_conversation_user_updated", table_name="v2_ai_conversation")
    op.drop_table("v2_ai_conversation")
    op.drop_index("idx_v2_ai_provider_college", table_name="v2_ai_provider_config")
    op.drop_table("v2_ai_provider_config")
