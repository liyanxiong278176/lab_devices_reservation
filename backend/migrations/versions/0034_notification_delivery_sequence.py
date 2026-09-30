"""Add a strict per-user delivery cursor for replayable notifications.

Revision ID: 0034_notification_sequence
Revises: 0033_knowledge_acl_metadata
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_notification_sequence"
down_revision: str | None = "0033_knowledge_acl_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification", sa.Column("delivery_sequence", sa.BigInteger(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE notification AS n "
            "JOIN ("
            "  SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY id) AS seq "
            "  FROM notification"
            ") AS ordered ON ordered.id = n.id "
            "SET n.delivery_sequence = ordered.seq"
        )
    )
    op.alter_column(
        "notification",
        "delivery_sequence",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_index(
        "uq_notification_user_delivery_sequence",
        "notification",
        ["user_id", "delivery_sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_notification_user_delivery_sequence", table_name="notification")
    op.drop_column("notification", "delivery_sequence")
