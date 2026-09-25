"""Keep return acceptance in handover status, not reservation status."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_return_pending_state"
down_revision: str | None = "0018_fulfillment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE reservation "
            "SET handover_status = 'RETURN_PENDING' "
            "WHERE status = 'RETURN_PENDING'"
        )
    )
    op.execute(
        sa.text("UPDATE reservation SET status = 'IN_USE' WHERE status = 'RETURN_PENDING'")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE reservation "
            "SET status = 'RETURN_PENDING' "
            "WHERE status = 'IN_USE' AND handover_status = 'RETURN_PENDING'"
        )
    )
