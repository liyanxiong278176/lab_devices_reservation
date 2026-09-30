"""Enforce ordered knowledge builds and audit explicit skips.

Revision ID: 0036_knowledge_build_ordering
Revises: 0035_ai_knowledge_build_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_knowledge_build_ordering"
down_revision: str | None = "0035_ai_knowledge_build_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "v2_knowledge_document",
        sa.Column("build_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "v2_knowledge_build_job",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("v2_knowledge_build_job", sa.Column("skipped_by", sa.BigInteger()))
    op.add_column("v2_knowledge_build_job", sa.Column("skipped_at", sa.DateTime()))
    op.add_column("v2_knowledge_build_job", sa.Column("skip_reason", sa.String(length=500)))

    op.execute(
        sa.text(
            "UPDATE v2_knowledge_build_job AS job "
            "JOIN ("
            "  SELECT ordered.id, ordered.document_sequence "
            "  FROM ("
            "    SELECT id, ROW_NUMBER() OVER ("
            "      PARTITION BY document_id ORDER BY queued_at, created_at, id"
            "    ) AS document_sequence "
            "    FROM v2_knowledge_build_job"
            "  ) AS ordered"
            ") AS ranked ON ranked.id = job.id "
            "SET job.sequence = ranked.document_sequence"
        )
    )
    op.execute(
        sa.text(
            "UPDATE v2_knowledge_document AS document "
            "LEFT JOIN ("
            "  SELECT document_id, MAX(sequence) AS latest_sequence "
            "  FROM v2_knowledge_build_job GROUP BY document_id"
            ") AS jobs ON jobs.document_id = document.id "
            "SET document.build_sequence = COALESCE(jobs.latest_sequence, 0)"
        )
    )

    op.alter_column(
        "v2_knowledge_document", "build_sequence", existing_type=sa.Integer(), server_default=None
    )
    op.alter_column(
        "v2_knowledge_build_job", "sequence", existing_type=sa.Integer(), server_default=None
    )
    op.create_foreign_key(
        "fk_v2_knowledge_build_job_skipped_by_user",
        "v2_knowledge_build_job",
        "sys_user",
        ["skipped_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uk_v2_knowledge_build_sequence",
        "v2_knowledge_build_job",
        ["document_id", "sequence"],
    )
    op.create_index(
        "idx_v2_knowledge_build_order",
        "v2_knowledge_build_job",
        ["document_id", "status", "sequence"],
    )
    op.create_index(
        "idx_v2_knowledge_build_status_queued",
        "v2_knowledge_build_job",
        ["status", "queued_at"],
    )
    op.create_index(
        "idx_v2_knowledge_build_status_completed",
        "v2_knowledge_build_job",
        ["status", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_v2_knowledge_build_status_completed", table_name="v2_knowledge_build_job")
    op.drop_index("idx_v2_knowledge_build_status_queued", table_name="v2_knowledge_build_job")
    op.drop_index("idx_v2_knowledge_build_order", table_name="v2_knowledge_build_job")
    op.drop_constraint(
        "uk_v2_knowledge_build_sequence", "v2_knowledge_build_job", type_="unique"
    )
    op.drop_constraint(
        "fk_v2_knowledge_build_job_skipped_by_user",
        "v2_knowledge_build_job",
        type_="foreignkey",
    )
    op.drop_column("v2_knowledge_build_job", "skip_reason")
    op.drop_column("v2_knowledge_build_job", "skipped_at")
    op.drop_column("v2_knowledge_build_job", "skipped_by")
    op.drop_column("v2_knowledge_build_job", "sequence")
    op.drop_column("v2_knowledge_document", "build_sequence")
