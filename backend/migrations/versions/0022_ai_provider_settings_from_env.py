"""Move AI provider settings and credentials out of MySQL into backend env configuration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ai_env_config"
down_revision: str | None = "0021_ai_durable_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "v2_ai_knowledge_index_state" not in tables:
        op.create_table(
            "v2_ai_knowledge_index_state",
            sa.Column("component", sa.String(24), nullable=False),
            sa.Column("collection_name", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("component"),
        )
        if "v2_ai_provider_config" in tables:
            op.execute(
                sa.text(
                    """
                    INSERT INTO v2_ai_knowledge_index_state (component, collection_name)
                    SELECT 'embedding', collection_name
                    FROM v2_ai_provider_config
                    WHERE scope_key = 'global:embedding' AND collection_name IS NOT NULL
                    LIMIT 1
                    """
                )
            )

    if "v2_ai_embedding_rebuild_job" in tables:
        job_columns = {
            column["name"] for column in inspector.get_columns("v2_ai_embedding_rebuild_job")
        }
        if {"target_api_key_encrypted", "source_api_key_encrypted"} & job_columns:
            # Stop old tasks before dropping their captured database credentials.
            op.execute(
                sa.text(
                    """
                    UPDATE v2_ai_embedding_rebuild_job
                    SET status = 'FAILED', error_code = 'AI_CONFIG_MOVED_TO_ENV',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE status IN ('QUEUED', 'RUNNING')
                    """
                )
            )
        if "config_fingerprint" not in job_columns:
            op.add_column(
                "v2_ai_embedding_rebuild_job",
                sa.Column("config_fingerprint", sa.String(64), nullable=False, server_default=""),
            )
        for column in (
            "target_api_key_encrypted",
            "source_api_key_encrypted",
            "source_enabled",
        ):
            if column in job_columns:
                op.drop_column("v2_ai_embedding_rebuild_job", column)
    if "v2_ai_provider_config" in tables:
        op.drop_table("v2_ai_provider_config")


def downgrade() -> None:
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
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", name="uk_v2_ai_provider_scope"),
    )
    op.create_index("idx_v2_ai_provider_college", "v2_ai_provider_config", ["college_id"])
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

    op.add_column(
        "v2_ai_embedding_rebuild_job",
        sa.Column("target_api_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "v2_ai_embedding_rebuild_job",
        sa.Column("source_api_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "v2_ai_embedding_rebuild_job",
        sa.Column("source_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_column("v2_ai_embedding_rebuild_job", "config_fingerprint")
    op.drop_table("v2_ai_knowledge_index_state")
