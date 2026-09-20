"""Make notification delivery at-least-once without duplicate user-visible rows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_reliability_indexes"
down_revision: str | None = "0003_repairs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("source_task_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ux_notification_source_task_key",
        "notification",
        ["source_task_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_notification_source_task_key", table_name="notification")
    op.drop_column("notification", "source_task_key")
