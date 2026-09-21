"""Release live day-index rows left by terminal reservations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_release_terminal_occupancy"
down_revision: str | None = "0016_backfill_device_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    reservation = sa.table(
        "reservation",
        sa.column("id", sa.BigInteger()),
        sa.column("status", sa.String(20)),
    )
    day = sa.table(
        "v2_reservation_day",
        sa.column("reservation_id", sa.BigInteger()),
    )
    bind = op.get_bind()
    terminal_ids = bind.execute(
        sa.select(reservation.c.id).where(
            reservation.c.status.in_(
                ("COMPLETED", "CANCELLED", "REJECTED", "VIOLATED", "NO_SHOW")
            )
        )
    ).scalars()
    for reservation_id in terminal_ids:
        bind.execute(
            day.delete().where(day.c.reservation_id == reservation_id)
        )


def downgrade() -> None:
    # Historical occupancy cannot be reconstructed safely after release.
    pass
