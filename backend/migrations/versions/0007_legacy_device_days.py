"""Add the natural-day reservation limit to legacy device tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_device_days"
down_revision: str | None = "0006_notification_ts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The old Spring schema stores an hourly limit instead.  The v2 API uses
    # inclusive natural-day reservations, so keep the compatibility column
    # additive and give existing equipment the same default as the ORM.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("device")}
    if "max_reservation_days" in columns:
        return

    op.add_column(
        "device",
        sa.Column("max_reservation_days", sa.Integer(), nullable=True, server_default="8"),
    )
    op.execute("UPDATE device SET max_reservation_days = 8 WHERE max_reservation_days IS NULL")
    op.alter_column(
        "device",
        "max_reservation_days",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="8",
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("device")}
    if "max_reservation_days" in columns:
        op.drop_column("device", "max_reservation_days")
