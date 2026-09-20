"""Reconcile legacy outbox tasks whose old rows had no aggregate key."""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_reconcile_legacy_outbox"
down_revision: str | None = "0009_seed_college_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Some legacy timeout rows predate aggregate_key and can only be linked by
    # the reservation id embedded in their JSON payload.
    op.execute(
        "UPDATE v2_outbox_task t JOIN reservation r "
        "ON CAST(JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.reservation_id')) AS UNSIGNED) = r.id "
        "SET t.college_id = r.college_id, "
        "t.payload = JSON_SET(t.payload, '$.college_id', r.college_id) "
        "WHERE t.college_id IS NULL OR t.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE v2_outbox_task t JOIN v2_repair_report r "
        "ON CAST(JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.repair_id')) AS UNSIGNED) = r.id "
        "SET t.college_id = r.college_id, "
        "t.payload = JSON_SET(t.payload, '$.college_id', r.college_id) "
        "WHERE t.college_id IS NULL OR t.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )


def downgrade() -> None:
    # Ownership reconciliation is intentionally not reversed.
    pass
