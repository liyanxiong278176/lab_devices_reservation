"""Backfill stable asset and QR identities for existing devices."""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_backfill_device_identity"
down_revision: str | None = "0015_non_ai_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    device = sa.table(
        "device",
        sa.column("id", sa.BigInteger()),
        sa.column("asset_code", sa.String(80)),
        sa.column("qr_token", sa.String(96)),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(device.c.id, device.c.asset_code, device.c.qr_token)
    ).mappings()
    for row in rows:
        values: dict[str, str] = {}
        if not row["asset_code"]:
            values["asset_code"] = f"LAB-{int(row['id']):06d}"
        if not row["qr_token"]:
            values["qr_token"] = f"lab-{secrets.token_urlsafe(42)}"
        if values:
            bind.execute(
                device.update().where(device.c.id == row["id"]).values(**values)
            )


def downgrade() -> None:
    # Stable identities are intentionally retained on downgrade so a rollback
    # cannot invalidate printed labels or external inventory references.
    pass
