"""Allow repeat attempts for a maintenance cycle after repair.

Revision ID: 0028_maintenance_retests
Revises: 0027_maint_asset_idx
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_maintenance_retests"
down_revision: str | None = "0027_maint_asset_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uk_v2_maintenance_record_cycle",
        "v2_device_maintenance_record",
        type_="unique",
    )


def downgrade() -> None:
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT plan_id, cycle_due_date "
            "FROM v2_device_maintenance_record "
            "GROUP BY plan_id, cycle_due_date HAVING COUNT(*) > 1"
            ") AS duplicate_cycles"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            "Cannot restore the maintenance-cycle unique constraint while a cycle "
            "has multiple attempts; preserve the retest history before downgrading."
        )
    op.create_unique_constraint(
        "uk_v2_maintenance_record_cycle",
        "v2_device_maintenance_record",
        ["plan_id", "cycle_due_date"],
    )
