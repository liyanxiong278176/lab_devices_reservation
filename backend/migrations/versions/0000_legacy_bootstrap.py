"""Create the compatibility base used by the v2 Alembic migration.

Existing installations may already have these tables; every operation is
guarded by an inspector check, so this revision is a no-op for them. A clean
installation can therefore run one Alembic chain from the Python service.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0000_legacy_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def _create(name: str, *columns: sa.Column, **kwargs) -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        op.create_table(name, *columns, **kwargs)


def upgrade() -> None:
    _create(
        "sys_role",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("role_code", sa.String(50), nullable=False),
        sa.Column("role_name", sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_code"),
    )
    _create(
        "sys_user",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password", sa.String(255), nullable=False),
        sa.Column("real_name", sa.String(50), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(100), nullable=True),
        sa.Column("user_type", sa.String(20), nullable=False, server_default="STUDENT"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    _create(
        "sys_user_role",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["sys_role.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    _create(
        "device_category",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create(
        "lab",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["manager_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create(
        "device",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("lab_id", sa.BigInteger(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("specs", sa.String(500), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="IDLE"),
        sa.Column("need_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["lab_id"], ["lab.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["device_category.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create(
        "reservation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("slot_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("approver_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("reject_reason", sa.String(500), nullable=True),
        sa.Column("check_in_at", sa.DateTime(), nullable=True),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"]),
        sa.ForeignKeyConstraint(["approver_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _create(
        "notification",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("related_id", sa.BigInteger(), nullable=True),
        sa.Column("related_type", sa.String(50), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # The tables may predate this revision. Keeping downgrade non-destructive
    # is safer than dropping a user's legacy data.
    pass
