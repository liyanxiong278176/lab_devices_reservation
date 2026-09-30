"""Add document heading tree and parent references for child chunks.

Revision ID: 0032_knowledge_parent_sections
Revises: 0031_ai_context_and_domain_terms
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_knowledge_parent_sections"
down_revision: str | None = "0031_ai_context_and_domain_terms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v2_knowledge_section",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_section_id", sa.BigInteger(), nullable=True),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=False),
        sa.Column("section_path", sa.String(length=2000), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["v2_knowledge_document.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_section_id"], ["v2_knowledge_section.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "section_index", name="uk_v2_knowledge_section_order"
        ),
    )
    op.create_index("ix_v2_knowledge_section_document_id", "v2_knowledge_section", ["document_id"])
    op.create_index(
        "ix_v2_knowledge_section_parent_section_id",
        "v2_knowledge_section",
        ["parent_section_id"],
    )
    op.add_column(
        "v2_knowledge_chunk",
        sa.Column("parent_section_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_v2_knowledge_chunk_parent_section",
        "v2_knowledge_chunk",
        "v2_knowledge_section",
        ["parent_section_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_v2_knowledge_chunk_parent_section_id",
        "v2_knowledge_chunk",
        ["parent_section_id"],
    )
    # 0030 already creates a named (run_id) index; the automatic column index
    # duplicates it and adds write/storage overhead without a query benefit.
    op.drop_index("ix_v2_ai_memory_recall_run_id", table_name="v2_ai_memory_recall")


def downgrade() -> None:
    op.drop_index("ix_v2_knowledge_chunk_parent_section_id", table_name="v2_knowledge_chunk")
    op.drop_constraint(
        "fk_v2_knowledge_chunk_parent_section", "v2_knowledge_chunk", type_="foreignkey"
    )
    op.drop_column("v2_knowledge_chunk", "parent_section_id")
    op.drop_index(
        "ix_v2_knowledge_section_parent_section_id", table_name="v2_knowledge_section"
    )
    op.drop_index("ix_v2_knowledge_section_document_id", table_name="v2_knowledge_section")
    op.drop_table("v2_knowledge_section")
    op.create_index(
        "ix_v2_ai_memory_recall_run_id", "v2_ai_memory_recall", ["run_id"]
    )
