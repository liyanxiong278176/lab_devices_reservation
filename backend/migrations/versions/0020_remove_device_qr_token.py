"""Remove the retired device QR credential."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_remove_device_qr_token"
down_revision: str | None = "0019_return_pending_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("device")}
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("device")}
    if "ix_device_qr_token" in indexes:
        op.drop_index("ix_device_qr_token", table_name="device")
    if "qr_token" in columns:
        op.drop_column("device", "qr_token")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("device")}
    if "qr_token" not in columns:
        op.add_column("device", sa.Column("qr_token", sa.String(length=96), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("device")}
    if "ix_device_qr_token" not in indexes:
        op.create_index("ix_device_qr_token", "device", ["qr_token"], unique=True)
