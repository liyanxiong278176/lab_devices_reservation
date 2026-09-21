"""Backfill tenant ownership and natural-day occupancy for legacy rows.

The original schema had no college columns and stored reservation windows as
timestamps. Existing deployments therefore need a deterministic default
tenant before v2 authorization can be enabled. Administrators can reassign
rows to their real colleges after the migration.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_backfill_legacy_tenant_data"
down_revision: str | None = "0004_reliability_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reference data is idempotent so this revision works for both a clean
    # Alembic database and an existing database that already has seed data.
    op.execute(
        "INSERT INTO sys_role (role_code, role_name) "
        "SELECT 'STUDENT', '学生' WHERE NOT EXISTS "
        "(SELECT 1 FROM sys_role WHERE role_code = 'STUDENT')"
    )
    op.execute(
        "INSERT INTO sys_role (role_code, role_name) "
        "SELECT 'LAB_ADMIN', '实验室管理员' WHERE NOT EXISTS "
        "(SELECT 1 FROM sys_role WHERE role_code = 'LAB_ADMIN')"
    )
    op.execute(
        "INSERT INTO sys_role (role_code, role_name) "
        "SELECT 'SYS_ADMIN', '系统管理员' WHERE NOT EXISTS "
        "(SELECT 1 FROM sys_role WHERE role_code = 'SYS_ADMIN')"
    )
    op.execute(
        "INSERT INTO device_category (name, parent_id, sort) "
        "SELECT '显微成像', 0, 1 WHERE NOT EXISTS "
        "(SELECT 1 FROM device_category WHERE name = '显微成像')"
    )
    op.execute(
        "INSERT INTO device_category (name, parent_id, sort) "
        "SELECT '光谱分析', 0, 2 WHERE NOT EXISTS "
        "(SELECT 1 FROM device_category WHERE name = '光谱分析')"
    )
    op.execute(
        "INSERT INTO device_category (name, parent_id, sort) "
        "SELECT '电子测量', 0, 3 WHERE NOT EXISTS "
        "(SELECT 1 FROM device_category WHERE name = '电子测量')"
    )

    # A legacy installation has no tenant identity. Keep all existing rows
    # visible in one explicitly named holding college instead of silently
    # denying access to every account after the v2 cutover.
    op.execute(
        "INSERT INTO college (code, name, status) "
        "SELECT 'LEGACY', '待分配学院', 1 WHERE NOT EXISTS "
        "(SELECT 1 FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE sys_user SET college_id = (SELECT id FROM college WHERE code = 'LEGACY') "
        "WHERE college_id IS NULL"
    )
    op.execute(
        "UPDATE lab SET college_id = (SELECT id FROM college WHERE code = 'LEGACY') "
        "WHERE college_id IS NULL"
    )
    op.execute(
        "UPDATE device d JOIN lab l ON l.id = d.lab_id "
        "SET d.college_id = l.college_id "
        "WHERE d.college_id IS NULL AND l.college_id IS NOT NULL"
    )
    op.execute(
        "UPDATE device SET college_id = (SELECT id FROM college WHERE code = 'LEGACY') "
        "WHERE college_id IS NULL"
    )
    op.execute(
        "UPDATE reservation r JOIN device d ON d.id = r.device_id "
        "SET r.college_id = d.college_id "
        "WHERE r.college_id IS NULL"
    )

    # Convert old timestamp ranges into one occupancy row per natural day.
    # MySQL 8 supports the recursive CTE and the v2 max-day setting keeps the
    # recursion bounded for newly created rows. INSERT IGNORE makes a rerun
    # safe if an operator had already backfilled part of the table manually.
    op.execute(
        "INSERT IGNORE INTO v2_reservation_day "
        "(reservation_id, device_id, date, slot_index) "
        "WITH RECURSIVE reservation_days "
        "(reservation_id, device_id, reservation_date, end_date) AS ("
        "SELECT id, device_id, start_date, end_date FROM reservation "
        "WHERE start_date IS NOT NULL AND end_date IS NOT NULL "
        "AND status IN ('PENDING', 'APPROVED', 'IN_USE') "
        "UNION ALL "
        "SELECT reservation_id, device_id, DATE_ADD(reservation_date, INTERVAL 1 DAY), end_date "
        "FROM reservation_days WHERE reservation_date < end_date"
        ") SELECT reservation_id, device_id, reservation_date, 0 FROM reservation_days"
    )


def downgrade() -> None:
    # The revision changes ownership of existing data; automatic rollback
    # would be destructive and is intentionally not supported.
    pass
