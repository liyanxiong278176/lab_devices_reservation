"""Complete the notification timestamp shape for existing databases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_notification_ts"
down_revision: str | None = "0005_backfill_legacy_tenant_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older installations only had created_at. The FastAPI
    # mapping uses the shared timestamp mixin, so add the missing column in a
    # rerunnable, non-destructive compatibility revision.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("notification")}
    if "updated_at" in columns:
        return

    op.add_column(
        "notification",
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    op.execute("UPDATE notification SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column(
        "notification",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
        server_default=sa.func.now(),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("notification")}
    if "updated_at" in columns:
        op.drop_column("notification", "updated_at")
