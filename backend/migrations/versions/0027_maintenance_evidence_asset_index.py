"""Index maintenance evidence references for downloads and cleanup checks.

Revision ID: 0027_maint_asset_idx
Revises: 0026_resv_dates
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_maint_asset_idx"
down_revision: str | None = "0026_resv_dates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_v2_device_maintenance_record_evidence_asset_id",
        "v2_device_maintenance_record",
        ["evidence_asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_v2_device_maintenance_record_evidence_asset_id",
        table_name="v2_device_maintenance_record",
    )
