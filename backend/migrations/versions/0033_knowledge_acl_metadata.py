"""Add role/resource ACL and incremental-index metadata for AI knowledge.

Revision ID: 0033_knowledge_acl_metadata
Revises: 0032_knowledge_parent_sections
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_knowledge_acl_metadata"
down_revision: str | None = "0032_knowledge_parent_sections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("v2_knowledge_document", sa.Column("lab_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "v2_knowledge_document", sa.Column("device_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("v2_knowledge_document", sa.Column("allowed_roles", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_v2_knowledge_document_lab",
        "v2_knowledge_document",
        "lab",
        ["lab_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_v2_knowledge_document_device",
        "v2_knowledge_document",
        "device",
        ["device_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_v2_knowledge_document_lab_id", "v2_knowledge_document", ["lab_id"])
    op.create_index("ix_v2_knowledge_document_device_id", "v2_knowledge_document", ["device_id"])
    op.create_index(
        "idx_v2_knowledge_scope_lab", "v2_knowledge_document", ["college_id", "lab_id"]
    )
    op.create_index(
        "idx_v2_knowledge_scope_device", "v2_knowledge_document", ["college_id", "device_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_v2_knowledge_scope_device", table_name="v2_knowledge_document")
    op.drop_index("idx_v2_knowledge_scope_lab", table_name="v2_knowledge_document")
    op.drop_index("ix_v2_knowledge_document_device_id", table_name="v2_knowledge_document")
    op.drop_index("ix_v2_knowledge_document_lab_id", table_name="v2_knowledge_document")
    op.drop_constraint(
        "fk_v2_knowledge_document_device", "v2_knowledge_document", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_v2_knowledge_document_lab", "v2_knowledge_document", type_="foreignkey"
    )
    op.drop_column("v2_knowledge_document", "allowed_roles")
    op.drop_column("v2_knowledge_document", "device_id")
    op.drop_column("v2_knowledge_document", "lab_id")
