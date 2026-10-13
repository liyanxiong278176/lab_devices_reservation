-- Older and Java notification envelopes use different task types/keys.
-- Remove pending deliveries and delivered history so deleted workflows cannot reappear.
DELETE FROM v2_outbox_task WHERE task_type IN ('NOTIFICATION','NOTIFICATION_DELIVER') AND (
 JSON_UNQUOTE(JSON_EXTRACT(payload,'$.related_type')) IN ('PENALTY','PENALTY_CASE','PENALTY_APPEAL','OVERDUE','MAINTENANCE','MAINTENANCE_PLAN','MAINTENANCE_RECORD')
 OR task_key LIKE 'notification:penalty:%' OR task_key LIKE 'notification:overdue:%'
 OR task_key LIKE '%:no-show');
DELETE FROM notification WHERE source_task_key LIKE 'notification:penalty:%'
 OR source_task_key LIKE 'notification:overdue:%' OR source_task_key LIKE '%:no-show';
