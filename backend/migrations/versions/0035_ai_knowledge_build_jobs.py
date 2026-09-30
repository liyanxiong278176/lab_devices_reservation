"""Add durable Celery build jobs and versioned knowledge staging rows.

Revision ID: 0035_ai_knowledge_build_jobs
Revises: 0034_notification_sequence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_ai_knowledge_build_jobs"
down_revision: str | None = "0034_notification_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "v2_knowledge_document",
        sa.Column("active_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "v2_knowledge_section",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "v2_knowledge_chunk",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        sa.text(
            "UPDATE v2_knowledge_document SET active_version=version "
            "WHERE status='PUBLISHED'"
        )
    )
    # Older published points already carried their document version in Qdrant
    # payload metadata. Recover it where present; old drafts have never been
    # served and start at version 1.
    op.execute(
        sa.text(
            "UPDATE v2_knowledge_chunk AS c "
            "JOIN v2_knowledge_document AS d ON d.id=c.document_id "
            "SET c.version=COALESCE(" 
            "  CAST(JSON_UNQUOTE(JSON_EXTRACT(c.metadata, '$.version')) AS UNSIGNED), "
            "  CASE WHEN d.status='PUBLISHED' THEN d.version ELSE 1 END)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE v2_knowledge_section AS s "
            "JOIN v2_knowledge_document AS d ON d.id=s.document_id "
            "SET s.version=CASE WHEN d.status='PUBLISHED' THEN d.version ELSE 1 END"
        )
    )
    op.alter_column(
        "v2_knowledge_section", "version", existing_type=sa.Integer(), server_default=None
    )
    op.alter_column(
        "v2_knowledge_chunk", "version", existing_type=sa.Integer(), server_default=None
    )

    op.drop_constraint(
        "uk_v2_knowledge_section_order", "v2_knowledge_section", type_="unique"
    )
    op.create_unique_constraint(
        "uk_v2_knowledge_section_order",
        "v2_knowledge_section",
        ["document_id", "version", "section_index"],
    )
    op.drop_constraint("uk_v2_knowledge_chunk_order", "v2_knowledge_chunk", type_="unique")
    op.create_unique_constraint(
        "uk_v2_knowledge_chunk_order",
        "v2_knowledge_chunk",
        ["document_id", "version", "chunk_index"],
    )

    op.create_table(
        "v2_knowledge_build_job",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("build_kind", sa.String(length=20), nullable=False),
        sa.Column("celery_task_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("completed_units", sa.Integer(), nullable=False),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("redeliveries", sa.Integer(), nullable=False),
        sa.Column("dispatch_recoveries", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("last_dispatched_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["v2_knowledge_document.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["college_id"], ["college.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["sys_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id", name="uk_v2_knowledge_build_celery_task"),
    )
    op.create_index(
        "ix_v2_knowledge_build_job_document_id",
        "v2_knowledge_build_job",
        ["document_id"],
    )
    op.create_index(
        "ix_v2_knowledge_build_job_college_id",
        "v2_knowledge_build_job",
        ["college_id"],
    )
    op.create_index(
        "ix_v2_knowledge_build_job_status",
        "v2_knowledge_build_job",
        ["status"],
    )
    op.create_index(
        "idx_v2_knowledge_build_document_created",
        "v2_knowledge_build_job",
        ["document_id", "created_at"],
    )
    op.create_index(
        "idx_v2_knowledge_build_status_heartbeat",
        "v2_knowledge_build_job",
        ["status", "heartbeat_at"],
    )
    op.create_index(
        "idx_v2_knowledge_build_tenant_status",
        "v2_knowledge_build_job",
        ["college_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_knowledge_build_tenant_status", table_name="v2_knowledge_build_job")
    op.drop_index("idx_v2_knowledge_build_status_heartbeat", table_name="v2_knowledge_build_job")
    op.drop_index("idx_v2_knowledge_build_document_created", table_name="v2_knowledge_build_job")
    op.drop_index("ix_v2_knowledge_build_job_status", table_name="v2_knowledge_build_job")
    op.drop_index("ix_v2_knowledge_build_job_college_id", table_name="v2_knowledge_build_job")
    op.drop_index("ix_v2_knowledge_build_job_document_id", table_name="v2_knowledge_build_job")
    op.drop_table("v2_knowledge_build_job")
    op.drop_constraint("uk_v2_knowledge_chunk_order", "v2_knowledge_chunk", type_="unique")
    op.create_unique_constraint(
        "uk_v2_knowledge_chunk_order", "v2_knowledge_chunk", ["document_id", "chunk_index"]
    )
    op.drop_constraint(
        "uk_v2_knowledge_section_order", "v2_knowledge_section", type_="unique"
    )
    op.create_unique_constraint(
        "uk_v2_knowledge_section_order",
        "v2_knowledge_section",
        ["document_id", "section_index"],
    )
    op.drop_column("v2_knowledge_chunk", "version")
    op.drop_column("v2_knowledge_section", "version")
    op.drop_column("v2_knowledge_document", "active_version")
