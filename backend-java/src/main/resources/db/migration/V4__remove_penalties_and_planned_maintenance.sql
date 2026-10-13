-- Owner-approved deletion of these modules and their history. Retained business records stay intact.
-- File deletion is resumable; this queue contains only paths pending deletion, not archived history.
CREATE TABLE v2_removed_workflow_file_cleanup (
  id BIGINT NOT NULL PRIMARY KEY,
  storage_path VARCHAR(500) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO v2_removed_workflow_file_cleanup (id,storage_path)
SELECT a.id,a.storage_path FROM v2_upload_asset a
WHERE (EXISTS (SELECT 1 FROM v2_device_maintenance_record m WHERE m.evidence_asset_id=a.id)
  OR EXISTS (SELECT 1 FROM v2_penalty_appeal p WHERE p.evidence LIKE CONCAT('%',a.asset_token,'%')))
AND NOT EXISTS (SELECT 1 FROM v2_device_document d WHERE d.asset_id=a.id)
AND NOT EXISTS (SELECT 1 FROM v2_device_qualification q WHERE q.asset_id=a.id)
AND NOT EXISTS (SELECT 1 FROM v2_repair_report r WHERE JSON_SEARCH(r.image_urls,'one',CONCAT('%',a.asset_token,'%')) IS NOT NULL)
AND NOT EXISTS (SELECT 1 FROM v2_repair_worklog r WHERE JSON_SEARCH(r.image_urls,'one',CONCAT('%',a.asset_token,'%')) IS NOT NULL)
AND NOT EXISTS (SELECT 1 FROM v2_device_handover h WHERE JSON_SEARCH(h.handover_image_urls,'one',CONCAT('%',a.asset_token,'%')) IS NOT NULL OR JSON_SEARCH(h.return_image_urls,'one',CONCAT('%',a.asset_token,'%')) IS NOT NULL)
AND NOT EXISTS (SELECT 1 FROM v2_reservation_inspection i WHERE JSON_SEARCH(i.image_urls,'one',CONCAT('%',a.asset_token,'%')) IS NOT NULL)
AND NOT EXISTS (SELECT 1 FROM device d WHERE d.image_url LIKE CONCAT('%',a.asset_token,'%'))
AND NOT EXISTS (SELECT 1 FROM v2_upload_asset other WHERE other.id<>a.id AND other.storage_path=a.storage_path);

DELETE FROM v2_outbox_task WHERE task_type IN ('RESERVATION_OVERDUE_START','RESERVATION_OVERDUE_PENALTY','MAINTENANCE_DUE','PENALTY_APPEAL_REMINDER')
  OR (task_type='NOTIFICATION_DELIVER' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.related_type')) IN ('PENALTY','PENALTY_CASE','PENALTY_APPEAL','OVERDUE','MAINTENANCE','MAINTENANCE_PLAN','MAINTENANCE_RECORD'));
UPDATE v2_outbox_task SET task_type='RESERVATION_UNCLAIMED_CANCEL' WHERE task_type='RESERVATION_NO_SHOW';
DELETE FROM notification WHERE related_type IN ('PENALTY','PENALTY_CASE','PENALTY_APPEAL','OVERDUE','MAINTENANCE','MAINTENANCE_PLAN','MAINTENANCE_RECORD');
DELETE FROM v2_audit_log WHERE target_type IN ('PENALTY','PENALTY_CASE','PENALTY_RULE','PENALTY_APPEAL','OVERDUE','MAINTENANCE_PLAN','MAINTENANCE_RECORD')
 OR action LIKE 'PENALTY_%' OR action LIKE 'OVERDUE_%' OR action LIKE 'MAINTENANCE_%';
DELETE rp FROM sys_role_permission rp JOIN sys_permission p ON p.id=rp.permission_id WHERE p.module IN ('penalty','penalties','maintenance') OR p.permission_code LIKE 'penalty:%' OR p.permission_code LIKE 'penalties:%' OR p.permission_code LIKE 'maintenance:%';
DELETE FROM sys_permission WHERE module IN ('penalty','penalties','maintenance') OR permission_code LIKE 'penalty:%' OR permission_code LIKE 'penalties:%' OR permission_code LIKE 'maintenance:%';
UPDATE sys_user SET credit_score=100,booking_blocked_until=NULL;
UPDATE v2_authz_version SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=1;

DROP TABLE v2_reservation_booking_restriction;
DROP TABLE v2_reservation_overdue_followup;
DROP TABLE v2_reservation_overdue;
DROP TABLE v2_penalty_appeal;
DROP TABLE v2_penalty_case;
DROP TABLE v2_penalty_rule_version;
DROP TABLE v2_penalty_grace_bounds;
DROP TABLE v2_credit_event;
DROP TABLE v2_college_credit_account;
DROP TABLE v2_device_maintenance_record;
DROP TABLE v2_device_maintenance_plan;
DELETE a FROM v2_upload_asset a JOIN v2_removed_workflow_file_cleanup c ON c.id=a.id;
