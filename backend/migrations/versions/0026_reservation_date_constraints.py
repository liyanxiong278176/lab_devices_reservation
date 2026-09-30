"""Require natural-day reservation dates in the database.

Revision ID: 0026_resv_dates
Revises: 0025_reservation_maintenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_resv_dates"
down_revision: str | None = "0025_reservation_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    null_rows = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM reservation "
            "WHERE start_date IS NULL OR end_date IS NULL"
        )
    ).scalar_one()
    if null_rows:
        raise RuntimeError(
            "Cannot enforce reservation date constraints: "
            f"{null_rows} reservation row(s) have a null start_date or end_date. "
            "Backfill or resolve them before retrying this migration."
        )

    op.alter_column(
        "reservation",
        "start_date",
        existing_type=sa.Date(),
        nullable=False,
    )
    op.alter_column(
        "reservation",
        "end_date",
        existing_type=sa.Date(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "reservation",
        "end_date",
        existing_type=sa.Date(),
        nullable=True,
    )
    op.alter_column(
        "reservation",
        "start_date",
        existing_type=sa.Date(),
        nullable=True,
    )
