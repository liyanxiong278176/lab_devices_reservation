"""Add evidence-backed fulfillment, waitlist offers, and purpose metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_fulfillment"
down_revision: str | None = "0017_release_terminal_occupancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Legacy NOTIFIED entries only received a message and never held a device
    # day. Put them back in queue order so future openings use the new offer flow.
    op.execute(
        sa.text(
            "UPDATE v2_reservation_waitlist "
            "SET status = 'WAITING', notified_at = NULL WHERE status = 'NOTIFIED'"
        )
    )
    op.add_column("device", sa.Column("accessory_checklist", sa.JSON(), nullable=True))

    op.add_column(
        "reservation",
        sa.Column(
            "purpose_category",
            sa.String(length=40),
            nullable=False,
            server_default="OTHER",
        ),
    )
    op.add_column("reservation", sa.Column("project_reference", sa.String(length=160)))

    op.add_column(
        "v2_reservation_waitlist",
        sa.Column("purpose_category", sa.String(length=40), nullable=False, server_default="OTHER"),
    )
    op.add_column(
        "v2_reservation_waitlist",
        sa.Column("project_reference", sa.String(length=160)),
    )
    op.create_table(
        "v2_reservation_waitlist_offer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("waitlist_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("college_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reservation_date", sa.Date(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id"], ["device.id"], name="fk_waitlist_offer_device", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["waitlist_id"],
            ["v2_reservation_waitlist.id"],
            name="fk_waitlist_offer_entry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["sys_user.id"], name="fk_waitlist_offer_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_v2_reservation_waitlist_offer"),
        sa.UniqueConstraint(
            "device_id", "reservation_date", name="uk_v2_waitlist_offer_device_day"
        ),
        sa.UniqueConstraint("waitlist_id", name="uk_v2_waitlist_offer_entry"),
    )
    op.create_index(
        "idx_v2_waitlist_offer_expiry",
        "v2_reservation_waitlist_offer",
        ["expires_at", "id"],
    )
    op.create_index(
        "ix_v2_reservation_waitlist_offer_college_id",
        "v2_reservation_waitlist_offer",
        ["college_id"],
    )
    op.create_index(
        "ix_v2_reservation_waitlist_offer_expires_at",
        "v2_reservation_waitlist_offer",
        ["expires_at"],
    )

    for column in (
        sa.Column("accessory_snapshot", sa.JSON(), nullable=True),
        sa.Column("handover_checklist", sa.JSON(), nullable=True),
        sa.Column("handover_image_urls", sa.JSON(), nullable=True),
        sa.Column("return_checklist", sa.JSON(), nullable=True),
        sa.Column("return_image_urls", sa.JSON(), nullable=True),
    ):
        op.add_column("v2_device_handover", column)

    op.add_column("v2_reservation_inspection", sa.Column("image_urls", sa.JSON(), nullable=True))
    op.add_column("v2_reservation_inspection", sa.Column("checklist", sa.JSON(), nullable=True))

    op.add_column(
        "v2_repair_report",
        sa.Column("reservation_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_v2_repair_report_reservation",
        "v2_repair_report",
        "reservation",
        ["reservation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uk_v2_repair_report_reservation",
        "v2_repair_report",
        ["reservation_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uk_v2_repair_report_reservation", "v2_repair_report", type_="unique")
    op.drop_constraint(
        "fk_v2_repair_report_reservation", "v2_repair_report", type_="foreignkey"
    )
    op.drop_column("v2_repair_report", "reservation_id")

    op.drop_column("v2_reservation_inspection", "checklist")
    op.drop_column("v2_reservation_inspection", "image_urls")

    for column in (
        "return_image_urls",
        "return_checklist",
        "handover_image_urls",
        "handover_checklist",
        "accessory_snapshot",
    ):
        op.drop_column("v2_device_handover", column)

    op.drop_index(
        "ix_v2_reservation_waitlist_offer_expires_at",
        table_name="v2_reservation_waitlist_offer",
    )
    op.drop_index(
        "ix_v2_reservation_waitlist_offer_college_id",
        table_name="v2_reservation_waitlist_offer",
    )
    op.drop_index("idx_v2_waitlist_offer_expiry", table_name="v2_reservation_waitlist_offer")
    op.drop_table("v2_reservation_waitlist_offer")
    op.drop_column("v2_reservation_waitlist", "project_reference")
    op.drop_column("v2_reservation_waitlist", "purpose_category")
    op.drop_column("reservation", "project_reference")
    op.drop_column("reservation", "purpose_category")
    op.drop_column("device", "accessory_checklist")
