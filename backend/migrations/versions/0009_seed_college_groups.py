"""Seed the real college tenants and repartition legacy catalog data.

The first tenant migration intentionally placed old rows in ``LEGACY`` so
that the v2 authorization layer could be enabled without losing visibility.
This revision replaces that holding tenant with the three colleges used by
the laboratory system and keeps all existing business records aligned with
their device/user scope.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_seed_college_groups"
down_revision: str | None = "0008_non_ai_perf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the seed repeatable for local environments that are rebuilt or
    # where an operator has already inserted one of the target colleges.
    op.execute(
        "INSERT INTO college (code, name, status) VALUES "
        "('CS', '计算机学院', 1) ON DUPLICATE KEY UPDATE "
        "name = VALUES(name), status = 1"
    )
    op.execute(
        "INSERT INTO college (code, name, status) VALUES "
        "('EE', '电气学院', 1) ON DUPLICATE KEY UPDATE "
        "name = VALUES(name), status = 1"
    )
    op.execute(
        "INSERT INTO college (code, name, status) VALUES "
        "('EIE', '电子信息学院', 1) ON DUPLICATE KEY UPDATE "
        "name = VALUES(name), status = 1"
    )

    # Labs are the stable ownership boundary for the catalog. A deterministic
    # id partition keeps the migration data-preserving while distributing the
    # existing legacy catalog across all three colleges. The modulo mapping is
    # also deliberately chosen so lab 12/device 270 belong to CS, which is
    # the device used by the local end-to-end verification account.
    op.execute(
        "UPDATE lab SET college_id = CASE MOD(id, 3) "
        "WHEN 0 THEN (SELECT id FROM college WHERE code = 'CS') "
        "WHEN 1 THEN (SELECT id FROM college WHERE code = 'EE') "
        "ELSE (SELECT id FROM college WHERE code = 'EIE') END "
        "WHERE college_id IS NULL OR college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE device d JOIN lab l ON l.id = d.lab_id "
        "SET d.college_id = l.college_id "
        "WHERE d.college_id IS NULL OR d.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE device SET college_id = CASE MOD(id, 3) "
        "WHEN 0 THEN (SELECT id FROM college WHERE code = 'CS') "
        "WHEN 1 THEN (SELECT id FROM college WHERE code = 'EE') "
        "ELSE (SELECT id FROM college WHERE code = 'EIE') END "
        "WHERE college_id IS NULL OR college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )

    # Keep the existing demo account in the same tenant as device 270 so the
    # normal-user/admin verification can exercise a real approval workflow.
    op.execute(
        "UPDATE sys_user SET college_id = "
        "(SELECT college_id FROM device WHERE id = 270) "
        "WHERE username = 'zhangsan'"
    )
    op.execute(
        "UPDATE sys_user SET college_id = CASE MOD(id, 3) "
        "WHEN 0 THEN (SELECT id FROM college WHERE code = 'CS') "
        "WHEN 1 THEN (SELECT id FROM college WHERE code = 'EE') "
        "ELSE (SELECT id FROM college WHERE code = 'EIE') END "
        "WHERE user_type <> 'SYS_ADMIN' AND (college_id IS NULL OR college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )

    # Reconcile all existing records that are scoped by a device, including
    # historical reservations and repair tickets.
    op.execute(
        "UPDATE reservation r JOIN device d ON d.id = r.device_id "
        "SET r.college_id = d.college_id "
        "WHERE r.college_id IS NULL OR r.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE v2_repair_report r JOIN device d ON d.id = r.device_id "
        "SET r.college_id = d.college_id "
        "WHERE r.college_id IS NULL OR r.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE notification n JOIN reservation r "
        "ON n.related_type = 'RESERVATION' AND n.related_id = r.id "
        "SET n.college_id = r.college_id "
        "WHERE n.college_id IS NULL OR n.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE notification n JOIN v2_repair_report r "
        "ON n.related_type = 'REPAIR' AND n.related_id = r.id "
        "SET n.college_id = r.college_id "
        "WHERE n.college_id IS NULL OR n.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE notification n JOIN sys_user u ON u.id = n.user_id "
        "SET n.college_id = u.college_id "
        "WHERE u.college_id IS NOT NULL AND (n.college_id IS NULL OR n.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )

    # Outbox payloads carry their own tenant value because they may execute
    # after the transaction commits. Update both the row and JSON payload so
    # old pending notification/timeout tasks cannot recreate LEGACY records.
    op.execute(
        "UPDATE v2_outbox_task t JOIN reservation r "
        "ON t.aggregate_key = CONCAT('reservation:', r.id) "
        "SET t.college_id = r.college_id, "
        "t.payload = JSON_SET(t.payload, '$.college_id', r.college_id) "
        "WHERE t.college_id IS NULL OR t.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
    op.execute(
        "UPDATE v2_outbox_task t JOIN v2_repair_report r "
        "ON t.aggregate_key = CONCAT('repair:', r.id) "
        "SET t.college_id = r.college_id, "
        "t.payload = JSON_SET(t.payload, '$.college_id', r.college_id) "
        "WHERE t.college_id IS NULL OR t.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY')"
    )
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

    # Preserve tenant scope for existing Agent Harness records without
    # changing global administrator conversations/configuration.
    op.execute(
        "UPDATE v2_ai_conversation c JOIN sys_user u ON u.id = c.user_id "
        "SET c.college_id = u.college_id "
        "WHERE u.college_id IS NOT NULL AND (c.college_id IS NULL OR c.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )
    op.execute(
        "UPDATE v2_ai_message m JOIN v2_ai_conversation c "
        "ON c.id = m.conversation_id "
        "SET m.college_id = c.college_id "
        "WHERE c.college_id IS NOT NULL AND (m.college_id IS NULL OR m.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )
    op.execute(
        "UPDATE v2_ai_run r JOIN v2_ai_conversation c "
        "ON c.id = r.conversation_id "
        "SET r.college_id = c.college_id "
        "WHERE c.college_id IS NOT NULL AND (r.college_id IS NULL OR r.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )
    op.execute(
        "UPDATE v2_ai_confirmation c JOIN v2_ai_conversation v "
        "ON v.id = c.conversation_id "
        "SET c.college_id = v.college_id "
        "WHERE v.college_id IS NOT NULL AND (c.college_id IS NULL OR c.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )
    op.execute(
        "UPDATE v2_knowledge_document d JOIN sys_user u ON u.id = d.created_by "
        "SET d.college_id = u.college_id "
        "WHERE u.college_id IS NOT NULL AND (d.college_id IS NULL OR d.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )
    op.execute(
        "UPDATE v2_knowledge_chunk c JOIN v2_knowledge_document d "
        "ON d.id = c.document_id "
        "SET c.college_id = d.college_id "
        "WHERE d.college_id IS NOT NULL AND (c.college_id IS NULL OR c.college_id = "
        "(SELECT id FROM college WHERE code = 'LEGACY'))"
    )

    # Keep the migration holding tenant for historical FK safety, but hide it
    # from the active college catalog so users only see the three real groups.
    op.execute("UPDATE college SET status = 0 WHERE code = 'LEGACY'")


def downgrade() -> None:
    # Reversing ownership of live business data would be destructive. The
    # three colleges and assignments are intentionally operator-managed after
    # this point.
    pass
