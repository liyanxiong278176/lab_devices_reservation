"""Persist AI run replay, LangGraph checkpoints, quotas and reviewed documents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_ai_durable_runtime"
down_revision: str | None = "0020_remove_device_qr_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.create_index(
            "ft_v2_knowledge_chunk_content",
            "v2_knowledge_chunk",
            ["content"],
            mysql_prefix="FULLTEXT",
        )
    op.add_column(
        "v2_ai_provider_config",
        sa.Column("user_daily_token_cap", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "v2_ai_provider_config",
        sa.Column("college_daily_token_cap", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "v2_ai_provider_config",
        sa.Column("global_daily_token_cap", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("v2_ai_provider_config", sa.Column("last_tested_at", sa.DateTime()))
    op.add_column("v2_ai_provider_config", sa.Column("collection_name", sa.String(120)))

    for name, column in (
        ("source_file_path", sa.String(1000)),
        ("source_file_name", sa.String(255)),
        ("source_sha256", sa.String(64)),
        ("parse_status", sa.String(24)),
        ("mineru_task_id", sa.String(100)),
        ("extracted_text", sa.Text()),
        ("reviewed_text", sa.Text()),
        ("reviewed_at", sa.DateTime()),
        ("reviewed_by", sa.BigInteger()),
        ("parse_error", sa.String(1000)),
    ):
        op.add_column("v2_knowledge_document", sa.Column(name, column, nullable=True))
    op.execute(
        "UPDATE v2_knowledge_document SET parse_status = 'NOT_REQUESTED' WHERE parse_status IS NULL"
    )
    op.alter_column(
        "v2_knowledge_document",
        "parse_status",
        existing_type=sa.String(24),
        nullable=False,
        server_default="NOT_REQUESTED",
    )
    op.create_foreign_key(
        "fk_v2_knowledge_reviewed_by_sys_user",
        "v2_knowledge_document",
        "sys_user",
        ["reviewed_by"],
        ["id"],
    )

    op.create_table(
        "v2_ai_run_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uk_v2_ai_event_run_sequence"),
    )
    op.create_index("ix_v2_ai_run_event_run_id", "v2_ai_run_event", ["run_id"])
    op.create_index("idx_v2_ai_event_run_sequence", "v2_ai_run_event", ["run_id", "sequence"])

    op.create_table(
        "v2_ai_usage_bucket",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type", "scope_id", "usage_date", name="uk_v2_ai_usage_scope_day"
        ),
    )
    op.create_index("idx_v2_ai_usage_date", "v2_ai_usage_bucket", ["usage_date", "scope_type"])

    op.create_table(
        "v2_ai_usage_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="RESERVED"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["v2_ai_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uk_v2_ai_usage_run"),
    )
    op.create_index("ix_v2_ai_usage_event_run_id", "v2_ai_usage_event", ["run_id"])
    op.create_index("idx_v2_ai_usage_user_date", "v2_ai_usage_event", ["user_id", "usage_date"])
    op.create_index(
        "idx_v2_ai_usage_college_date", "v2_ai_usage_event", ["college_id", "usage_date"]
    )

    op.create_table(
        "v2_ai_aux_usage_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("component", sa.String(20), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="SUCCEEDED"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uk_v2_ai_aux_usage_event_key"),
    )
    op.create_index("ix_v2_ai_aux_usage_event_user_id", "v2_ai_aux_usage_event", ["user_id"])
    op.create_index("ix_v2_ai_aux_usage_event_college_id", "v2_ai_aux_usage_event", ["college_id"])
    op.create_index("ix_v2_ai_aux_usage_event_usage_date", "v2_ai_aux_usage_event", ["usage_date"])
    op.create_index(
        "idx_v2_ai_aux_usage_day",
        "v2_ai_aux_usage_event",
        ["usage_date", "component", "college_id"],
    )

    op.create_table(
        "v2_ai_embedding_rebuild_job",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_key", sa.String(80), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("source_collection", sa.String(120), nullable=False),
        sa.Column("target_collection", sa.String(120), nullable=False),
        sa.Column("target_model", sa.String(120), nullable=False),
        sa.Column("target_base_url", sa.String(500), nullable=False),
        sa.Column("target_api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("source_model", sa.String(120), nullable=False),
        sa.Column("source_base_url", sa.String(500), nullable=True),
        sa.Column("source_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("source_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_chunk_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_key", name="uk_v2_ai_embedding_job_key"),
        sa.UniqueConstraint("target_collection", name="uk_v2_ai_embedding_target_collection"),
    )
    op.create_index(
        "ix_v2_ai_embedding_rebuild_job_requested_by",
        "v2_ai_embedding_rebuild_job",
        ["requested_by"],
    )
    op.create_index(
        "ix_v2_ai_embedding_rebuild_job_college_id",
        "v2_ai_embedding_rebuild_job",
        ["college_id"],
    )
    op.create_index(
        "ix_v2_ai_embedding_rebuild_job_status",
        "v2_ai_embedding_rebuild_job",
        ["status"],
    )
    op.create_index(
        "idx_v2_ai_embedding_job_status",
        "v2_ai_embedding_rebuild_job",
        ["status", "created_at"],
    )

    op.create_table(
        "v2_ai_checkpoint",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("checkpoint_ns", sa.String(128), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(128), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(255), nullable=True),
        sa.Column("checkpoint_type", sa.String(80), nullable=False),
        sa.Column("checkpoint_blob", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.String(80), nullable=False),
        sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id", "checkpoint_ns", "checkpoint_id", name="uk_v2_ai_checkpoint"
        ),
    )
    op.create_index(
        "idx_v2_ai_checkpoint_head",
        "v2_ai_checkpoint",
        ["thread_id", "checkpoint_ns", "checkpoint_id"],
    )

    op.create_table(
        "v2_ai_checkpoint_write",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("checkpoint_ns", sa.String(128), nullable=False, server_default=""),
        sa.Column("checkpoint_id", sa.String(128), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("write_index", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(255), nullable=False),
        sa.Column("value_type", sa.String(80), nullable=False),
        sa.Column("value_blob", sa.LargeBinary(), nullable=False),
        sa.Column("task_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "write_index",
            name="uk_v2_ai_checkpoint_write",
        ),
    )
    op.create_index(
        "idx_v2_ai_checkpoint_write_parent",
        "v2_ai_checkpoint_write",
        ["thread_id", "checkpoint_ns", "checkpoint_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.drop_index("ft_v2_knowledge_chunk_content", table_name="v2_knowledge_chunk")
    op.drop_index("idx_v2_ai_embedding_job_status", table_name="v2_ai_embedding_rebuild_job")
    op.drop_index("ix_v2_ai_embedding_rebuild_job_status", table_name="v2_ai_embedding_rebuild_job")
    op.drop_index(
        "ix_v2_ai_embedding_rebuild_job_college_id", table_name="v2_ai_embedding_rebuild_job"
    )
    op.drop_index(
        "ix_v2_ai_embedding_rebuild_job_requested_by", table_name="v2_ai_embedding_rebuild_job"
    )
    op.drop_table("v2_ai_embedding_rebuild_job")
    op.drop_index("idx_v2_ai_aux_usage_day", table_name="v2_ai_aux_usage_event")
    op.drop_index("ix_v2_ai_aux_usage_event_usage_date", table_name="v2_ai_aux_usage_event")
    op.drop_index("ix_v2_ai_aux_usage_event_college_id", table_name="v2_ai_aux_usage_event")
    op.drop_index("ix_v2_ai_aux_usage_event_user_id", table_name="v2_ai_aux_usage_event")
    op.drop_table("v2_ai_aux_usage_event")
    op.drop_index("idx_v2_ai_checkpoint_write_parent", table_name="v2_ai_checkpoint_write")
    op.drop_table("v2_ai_checkpoint_write")
    op.drop_index("idx_v2_ai_checkpoint_head", table_name="v2_ai_checkpoint")
    op.drop_table("v2_ai_checkpoint")
    op.drop_index("idx_v2_ai_usage_college_date", table_name="v2_ai_usage_event")
    op.drop_index("idx_v2_ai_usage_user_date", table_name="v2_ai_usage_event")
    op.drop_index("ix_v2_ai_usage_event_run_id", table_name="v2_ai_usage_event")
    op.drop_table("v2_ai_usage_event")
    op.drop_index("idx_v2_ai_usage_date", table_name="v2_ai_usage_bucket")
    op.drop_table("v2_ai_usage_bucket")
    op.drop_index("idx_v2_ai_event_run_sequence", table_name="v2_ai_run_event")
    op.drop_index("ix_v2_ai_run_event_run_id", table_name="v2_ai_run_event")
    op.drop_table("v2_ai_run_event")
    op.drop_constraint(
        "fk_v2_knowledge_reviewed_by_sys_user", "v2_knowledge_document", type_="foreignkey"
    )
    for column in (
        "parse_error",
        "reviewed_by",
        "reviewed_at",
        "reviewed_text",
        "extracted_text",
        "mineru_task_id",
        "parse_status",
        "source_sha256",
        "source_file_name",
        "source_file_path",
    ):
        op.drop_column("v2_knowledge_document", column)
    for column in (
        "collection_name",
        "last_tested_at",
        "global_daily_token_cap",
        "college_daily_token_cap",
        "user_daily_token_cap",
    ):
        op.drop_column("v2_ai_provider_config", column)
