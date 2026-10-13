-- Snapshot of actual MySQL 8 Alembic head 0038_penalties_overdue.
SET FOREIGN_KEY_CHECKS=0;
CREATE TABLE `college` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `code` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` int NOT NULL DEFAULT '1',
  `manager_id` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  UNIQUE KEY `name` (`name`),
  KEY `idx_college_manager_id_v2` (`manager_id`),
  CONSTRAINT `fk_college_manager_v2` FOREIGN KEY (`manager_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `device` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `lab_id` bigint DEFAULT NULL,
  `category_id` bigint DEFAULT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `brand` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `model` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `specs` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `image_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'IDLE',
  `need_approval` tinyint(1) NOT NULL DEFAULT '0',
  `description` text COLLATE utf8mb4_unicode_ci,
  `tags` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `college_id` bigint DEFAULT NULL,
  `max_reservation_days` int NOT NULL DEFAULT '8',
  `asset_code` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `serial_number` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `purchase_date` date DEFAULT NULL,
  `warranty_until` date DEFAULT NULL,
  `allow_external_loan` tinyint(1) NOT NULL DEFAULT '0',
  `risk_level` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'STANDARD',
  `requires_safety_ack` tinyint(1) NOT NULL DEFAULT '0',
  `requires_qualification` tinyint(1) NOT NULL DEFAULT '0',
  `max_advance_days` int DEFAULT NULL,
  `accessory_checklist` json DEFAULT NULL,
  `pool_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_device_asset_code` (`asset_code`),
  KEY `lab_id` (`lab_id`),
  KEY `category_id` (`category_id`),
  KEY `idx_device_college_id_v2` (`college_id`),
  KEY `idx_device_college_status_id_v2` (`college_id`,`status`,`id`),
  KEY `idx_device_college_lab_id_v2` (`college_id`,`lab_id`,`id`),
  KEY `ix_device_pool_id` (`pool_id`),
  CONSTRAINT `device_ibfk_1` FOREIGN KEY (`lab_id`) REFERENCES `lab` (`id`),
  CONSTRAINT `device_ibfk_2` FOREIGN KEY (`category_id`) REFERENCES `device_category` (`id`),
  CONSTRAINT `fk_device_college_v2` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `fk_device_pool_id` FOREIGN KEY (`pool_id`) REFERENCES `v2_device_pool` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `device_category` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `parent_id` bigint NOT NULL DEFAULT '0',
  `sort` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `lab` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `location` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `manager_id` bigint DEFAULT NULL,
  `description` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` int NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `college_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `manager_id` (`manager_id`),
  KEY `idx_lab_college_id_v2` (`college_id`),
  CONSTRAINT `fk_lab_college_v2` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `lab_ibfk_1` FOREIGN KEY (`manager_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `notification` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` varchar(1000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `related_id` bigint DEFAULT NULL,
  `related_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_read` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `college_id` bigint DEFAULT NULL,
  `source_task_key` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `delivery_sequence` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_notification_user_delivery_sequence` (`user_id`,`delivery_sequence`),
  UNIQUE KEY `ux_notification_source_task_key` (`source_task_key`),
  KEY `idx_notification_college_v2` (`college_id`),
  KEY `idx_notification_user_read_id_v2` (`user_id`,`is_read`,`id`),
  CONSTRAINT `notification_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `reservation` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `purpose` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `start_time` datetime DEFAULT NULL,
  `end_time` datetime DEFAULT NULL,
  `slot_count` int NOT NULL DEFAULT '1',
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `approver_id` bigint DEFAULT NULL,
  `approved_at` datetime DEFAULT NULL,
  `reject_reason` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `check_in_at` datetime DEFAULT NULL,
  `check_out_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `college_id` bigint DEFAULT NULL,
  `start_date` date NOT NULL,
  `end_date` date NOT NULL,
  `batch_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `handover_status` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'NOT_REQUIRED',
  `safety_acknowledged_at` datetime DEFAULT NULL,
  `safety_document_version` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `purpose_category` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'OTHER',
  `project_reference` varchar(160) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `device_id` (`device_id`),
  KEY `approver_id` (`approver_id`),
  KEY `idx_reservation_college_v2` (`college_id`),
  KEY `idx_reservation_batch_v2` (`batch_id`),
  KEY `idx_reservation_dates_v2` (`start_date`,`end_date`),
  KEY `idx_reservation_user_id_v2` (`user_id`,`id`),
  KEY `idx_reservation_college_status_id_v2` (`college_id`,`status`,`id`),
  CONSTRAINT `reservation_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `reservation_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `reservation_ibfk_3` FOREIGN KEY (`approver_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sys_permission` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `permission_code` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `permission_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `module` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_sys_permission_permission_code` (`permission_code`),
  KEY `ix_sys_permission_module` (`module`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sys_role` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `role_code` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role_name` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_system` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `role_code` (`role_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sys_role_permission` (
  `role_id` bigint NOT NULL,
  `permission_id` bigint NOT NULL,
  PRIMARY KEY (`role_id`,`permission_id`),
  KEY `permission_id` (`permission_id`),
  CONSTRAINT `sys_role_permission_ibfk_1` FOREIGN KEY (`permission_id`) REFERENCES `sys_permission` (`id`) ON DELETE CASCADE,
  CONSTRAINT `sys_role_permission_ibfk_2` FOREIGN KEY (`role_id`) REFERENCES `sys_role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sys_user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `real_name` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `phone` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `email` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `user_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'STUDENT',
  `status` int NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `college_id` bigint DEFAULT NULL,
  `credit_score` int NOT NULL DEFAULT '100',
  `booking_blocked_until` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  KEY `idx_sys_user_college_id_v2` (`college_id`),
  CONSTRAINT `fk_sys_user_college_v2` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `sys_user_role` (
  `user_id` bigint NOT NULL,
  `role_id` bigint NOT NULL,
  PRIMARY KEY (`user_id`,`role_id`),
  KEY `role_id` (`role_id`),
  CONSTRAINT `sys_user_role_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `sys_user_role_ibfk_2` FOREIGN KEY (`role_id`) REFERENCES `sys_role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_audit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint DEFAULT NULL,
  `college_id` bigint DEFAULT NULL,
  `action` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `target_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `target_id` bigint DEFAULT NULL,
  `detail` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  KEY `idx_v2_audit_scope_created` (`college_id`,`created_at`),
  KEY `idx_v2_audit_target_created` (`target_type`,`target_id`,`created_at`),
  CONSTRAINT `v2_audit_log_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_authz_version` (
  `id` int NOT NULL,
  `version` bigint NOT NULL DEFAULT '1',
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  CONSTRAINT `ck_v2_authz_singleton` CHECK ((`id` = 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_college_credit_account` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `college_id` bigint NOT NULL,
  `points` int NOT NULL DEFAULT '100',
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_college_credit_user_college` (`user_id`,`college_id`),
  KEY `ix_v2_college_credit_account_user_id` (`user_id`),
  KEY `ix_v2_college_credit_account_college_id` (`college_id`),
  KEY `idx_v2_college_credit_college_points` (`college_id`,`points`),
  CONSTRAINT `v2_college_credit_account_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_college_credit_account_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_credit_event` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `reservation_id` bigint DEFAULT NULL,
  `event_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `points` int NOT NULL,
  `reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `operator_id` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `reservation_id` (`reservation_id`),
  KEY `operator_id` (`operator_id`),
  KEY `idx_v2_credit_event_user_created` (`user_id`,`created_at`),
  CONSTRAINT `v2_credit_event_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_credit_event_ibfk_2` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`),
  CONSTRAINT `v2_credit_event_ibfk_3` FOREIGN KEY (`operator_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_document` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `asset_id` bigint NOT NULL,
  `document_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'MANUAL',
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `created_by` bigint NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `version` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '1.0',
  `requires_ack` tinyint(1) NOT NULL DEFAULT '0',
  `published_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `asset_id` (`asset_id`),
  KEY `created_by` (`created_by`),
  KEY `idx_v2_device_document_device_active` (`device_id`,`active`,`created_at`),
  KEY `idx_v2_device_document_college_active` (`college_id`,`active`,`created_at`),
  CONSTRAINT `v2_device_document_ibfk_1` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_document_ibfk_2` FOREIGN KEY (`asset_id`) REFERENCES `v2_upload_asset` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_document_ibfk_3` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_document_ack` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `document_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `reservation_id` bigint DEFAULT NULL,
  `document_version` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `acknowledged_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_device_document_ack_user` (`document_id`,`user_id`),
  KEY `device_id` (`device_id`),
  KEY `reservation_id` (`reservation_id`),
  KEY `idx_v2_device_document_ack_user` (`user_id`,`acknowledged_at`),
  CONSTRAINT `v2_device_document_ack_ibfk_1` FOREIGN KEY (`document_id`) REFERENCES `v2_device_document` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_document_ack_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_device_document_ack_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_document_ack_ibfk_4` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_handover` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `handover_by` bigint DEFAULT NULL,
  `handover_at` datetime DEFAULT NULL,
  `handover_condition` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `handover_note` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `returned_by` bigint DEFAULT NULL,
  `returned_at` datetime DEFAULT NULL,
  `return_condition` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `return_note` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `accessory_snapshot` json DEFAULT NULL,
  `handover_checklist` json DEFAULT NULL,
  `handover_image_urls` json DEFAULT NULL,
  `return_checklist` json DEFAULT NULL,
  `return_image_urls` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_device_handover_reservation` (`reservation_id`),
  KEY `user_id` (`user_id`),
  KEY `handover_by` (`handover_by`),
  KEY `returned_by` (`returned_by`),
  KEY `idx_v2_device_handover_device_status` (`device_id`,`status`,`created_at`),
  KEY `idx_v2_device_handover_scope_status` (`college_id`,`status`),
  CONSTRAINT `v2_device_handover_ibfk_1` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_handover_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_device_handover_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_handover_ibfk_4` FOREIGN KEY (`handover_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_handover_ibfk_5` FOREIGN KEY (`returned_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_maintenance_plan` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `plan_type` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(160) COLLATE utf8mb4_unicode_ci NOT NULL,
  `interval_value` int NOT NULL,
  `interval_unit` varchar(12) COLLATE utf8mb4_unicode_ci NOT NULL,
  `due_date` date NOT NULL,
  `downtime_start` date DEFAULT NULL,
  `downtime_end` date DEFAULT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `due_notice_sent_at` datetime DEFAULT NULL,
  `created_by` bigint NOT NULL,
  `updated_by` bigint NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `created_by` (`created_by`),
  KEY `updated_by` (`updated_by`),
  KEY `idx_v2_maintenance_device_active` (`device_id`,`active`),
  KEY `idx_v2_maintenance_due_active` (`active`,`due_date`,`plan_type`),
  KEY `idx_v2_maintenance_scope` (`college_id`,`active`,`id`),
  CONSTRAINT `v2_device_maintenance_plan_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_device_maintenance_plan_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_maintenance_plan_ibfk_3` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_maintenance_plan_ibfk_4` FOREIGN KEY (`updated_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_maintenance_record` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `plan_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `cycle_due_date` date NOT NULL,
  `completed_date` date NOT NULL,
  `downtime_start` date DEFAULT NULL,
  `downtime_end` date DEFAULT NULL,
  `result` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `notes` varchar(2000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `performed_by` bigint NOT NULL,
  `evidence_asset_id` bigint DEFAULT NULL,
  `repair_report_id` bigint DEFAULT NULL,
  `idempotency_key` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `request_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_maintenance_record_request` (`plan_id`,`idempotency_key`),
  KEY `performed_by` (`performed_by`),
  KEY `idx_v2_maintenance_record_plan_date` (`plan_id`,`cycle_due_date`,`id`),
  KEY `idx_v2_maintenance_record_device_date` (`device_id`,`completed_date`,`id`),
  KEY `ix_v2_device_maintenance_record_college_id` (`college_id`),
  KEY `ix_v2_device_maintenance_record_repair_report_id` (`repair_report_id`),
  KEY `ix_v2_device_maintenance_record_evidence_asset_id` (`evidence_asset_id`),
  CONSTRAINT `v2_device_maintenance_record_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_device_maintenance_record_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_maintenance_record_ibfk_3` FOREIGN KEY (`evidence_asset_id`) REFERENCES `v2_upload_asset` (`id`),
  CONSTRAINT `v2_device_maintenance_record_ibfk_4` FOREIGN KEY (`plan_id`) REFERENCES `v2_device_maintenance_plan` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_maintenance_record_ibfk_5` FOREIGN KEY (`performed_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_maintenance_record_ibfk_6` FOREIGN KEY (`repair_report_id`) REFERENCES `v2_repair_report` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_pool` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `lab_id` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `lab_id` (`lab_id`),
  KEY `idx_v2_device_pool_college_lab_id` (`college_id`,`lab_id`,`id`),
  CONSTRAINT `v2_device_pool_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_device_pool_ibfk_2` FOREIGN KEY (`lab_id`) REFERENCES `lab` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_qualification` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `device_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `qualification_type` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'TRAINING',
  `asset_id` bigint DEFAULT NULL,
  `valid_until` date DEFAULT NULL,
  `reviewed_by` bigint DEFAULT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `note` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_device_qualification_user` (`device_id`,`user_id`),
  KEY `asset_id` (`asset_id`),
  KEY `reviewed_by` (`reviewed_by`),
  KEY `idx_v2_device_qualification_scope_status` (`college_id`,`status`,`valid_until`),
  KEY `idx_v2_device_qualification_user_status` (`user_id`,`status`,`valid_until`),
  CONSTRAINT `v2_device_qualification_ibfk_1` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_qualification_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_device_qualification_ibfk_3` FOREIGN KEY (`asset_id`) REFERENCES `v2_upload_asset` (`id`),
  CONSTRAINT `v2_device_qualification_ibfk_4` FOREIGN KEY (`reviewed_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_device_status_history` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `old_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `new_status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `operator_id` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `operator_id` (`operator_id`),
  KEY `idx_v2_device_status_history_device_created` (`device_id`,`created_at`),
  KEY `idx_v2_device_status_history_college` (`college_id`),
  CONSTRAINT `v2_device_status_history_ibfk_1` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_device_status_history_ibfk_2` FOREIGN KEY (`operator_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_export_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `requester_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `export_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `filters` json DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `file_token` varchar(96) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `file_path` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `row_count` int NOT NULL DEFAULT '0',
  `error` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `completed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_export_task_file_token` (`file_token`),
  KEY `idx_v2_export_task_user_status_created` (`requester_id`,`status`,`created_at`),
  KEY `idx_v2_export_task_status_created` (`status`,`created_at`),
  CONSTRAINT `v2_export_task_ibfk_1` FOREIGN KEY (`requester_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_idempotency_key` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `key` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `request_hash` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `response_code` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `response_body` json DEFAULT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_idempotency_user_key` (`user_id`,`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_outbox_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `task_key` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `task_type` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `payload` json NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `attempts` int NOT NULL DEFAULT '0',
  `execute_at` datetime NOT NULL,
  `claimed_at` datetime DEFAULT NULL,
  `completed_at` datetime DEFAULT NULL,
  `last_error` text COLLATE utf8mb4_unicode_ci,
  `aggregate_key` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_outbox_task_key` (`task_key`),
  KEY `idx_v2_outbox_aggregate_status` (`aggregate_key`,`status`,`id`),
  KEY `idx_v2_outbox_status_execute` (`status`,`execute_at`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_penalty_appeal` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `penalty_case_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint NOT NULL,
  `attempt_number` int NOT NULL,
  `reason` varchar(2000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `evidence` varchar(2000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `reviewer_id` bigint DEFAULT NULL,
  `result` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `result_reason` varchar(2000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `adjusted_points_delta` int DEFAULT NULL,
  `adjusted_block_days` int DEFAULT NULL,
  `submitted_at` datetime NOT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_penalty_appeal_attempt` (`penalty_case_id`,`attempt_number`),
  KEY `reviewer_id` (`reviewer_id`),
  KEY `ix_v2_penalty_appeal_penalty_case_id` (`penalty_case_id`),
  KEY `ix_v2_penalty_appeal_user_id` (`user_id`),
  KEY `ix_v2_penalty_appeal_college_id` (`college_id`),
  KEY `ix_v2_penalty_appeal_status` (`status`),
  KEY `idx_v2_penalty_appeal_college_status` (`college_id`,`status`,`submitted_at`),
  KEY `idx_v2_penalty_appeal_user` (`user_id`,`submitted_at`),
  CONSTRAINT `v2_penalty_appeal_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_penalty_appeal_ibfk_2` FOREIGN KEY (`penalty_case_id`) REFERENCES `v2_penalty_case` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_penalty_appeal_ibfk_3` FOREIGN KEY (`reviewer_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_penalty_appeal_ibfk_4` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_penalty_case` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint NOT NULL,
  `lab_id` bigint DEFAULT NULL,
  `device_id` bigint NOT NULL,
  `violation_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `reason` varchar(1000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `event_at` datetime NOT NULL,
  `rule_version_id` bigint DEFAULT NULL,
  `occurrence_number` int NOT NULL DEFAULT '1',
  `points_delta` int NOT NULL DEFAULT '0',
  `reservation_block_days` int NOT NULL DEFAULT '0',
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ACTIVE',
  `confirmed_by` bigint DEFAULT NULL,
  `applied_at` datetime NOT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_penalty_reservation_type` (`reservation_id`,`violation_type`),
  KEY `confirmed_by` (`confirmed_by`),
  KEY `rule_version_id` (`rule_version_id`),
  KEY `ix_v2_penalty_case_reservation_id` (`reservation_id`),
  KEY `ix_v2_penalty_case_user_id` (`user_id`),
  KEY `ix_v2_penalty_case_college_id` (`college_id`),
  KEY `ix_v2_penalty_case_lab_id` (`lab_id`),
  KEY `ix_v2_penalty_case_device_id` (`device_id`),
  KEY `ix_v2_penalty_case_event_at` (`event_at`),
  KEY `ix_v2_penalty_case_status` (`status`),
  KEY `idx_v2_penalty_user_college_event` (`user_id`,`college_id`,`event_at`),
  KEY `idx_v2_penalty_college_status` (`college_id`,`status`,`applied_at`),
  CONSTRAINT `v2_penalty_case_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_2` FOREIGN KEY (`confirmed_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_3` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_4` FOREIGN KEY (`lab_id`) REFERENCES `lab` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_5` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_6` FOREIGN KEY (`rule_version_id`) REFERENCES `v2_penalty_rule_version` (`id`),
  CONSTRAINT `v2_penalty_case_ibfk_7` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_penalty_grace_bounds` (
  `id` int NOT NULL,
  `minimum_days` int NOT NULL,
  `maximum_days` int NOT NULL,
  `updated_by` bigint DEFAULT NULL,
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `updated_by` (`updated_by`),
  CONSTRAINT `v2_penalty_grace_bounds_ibfk_1` FOREIGN KEY (`updated_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_penalty_rule_version` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `college_id` bigint NOT NULL,
  `version` int NOT NULL,
  `effective_at` datetime NOT NULL,
  `grace_days` int NOT NULL DEFAULT '0',
  `tiers` json NOT NULL,
  `created_by` bigint NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_penalty_rule_college_version` (`college_id`,`version`),
  KEY `created_by` (`created_by`),
  KEY `ix_v2_penalty_rule_version_college_id` (`college_id`),
  KEY `ix_v2_penalty_rule_version_effective_at` (`effective_at`),
  KEY `idx_v2_penalty_rule_effective` (`college_id`,`effective_at`,`version`),
  CONSTRAINT `v2_penalty_rule_version_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_penalty_rule_version_ibfk_2` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_refresh_session` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `token_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `expires_at` datetime NOT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `replaced_by` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `family_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_refresh_token_id` (`token_id`),
  KEY `idx_v2_refresh_user_active` (`user_id`,`revoked_at`,`expires_at`),
  KEY `idx_v2_refresh_family_active` (`family_id`,`revoked_at`,`expires_at`),
  CONSTRAINT `v2_refresh_session_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_repair_report` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `college_id` bigint DEFAULT NULL,
  `device_id` bigint NOT NULL,
  `reporter_id` bigint NOT NULL,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `image_urls` json DEFAULT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'PENDING',
  `handler_id` bigint DEFAULT NULL,
  `resolution_note` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `taken_at` datetime DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  `priority` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'NORMAL',
  `response_due_at` datetime DEFAULT NULL,
  `resolve_due_at` datetime DEFAULT NULL,
  `user_confirmed_at` datetime DEFAULT NULL,
  `user_confirmation_note` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `closed_at` datetime DEFAULT NULL,
  `reservation_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_repair_report_reservation` (`reservation_id`),
  KEY `handler_id` (`handler_id`),
  KEY `idx_v2_repair_scope_status` (`college_id`,`status`,`created_at`),
  KEY `idx_v2_repair_reporter` (`reporter_id`,`created_at`),
  KEY `idx_v2_repair_device_status` (`device_id`,`status`),
  KEY `ix_v2_repair_report_priority` (`priority`),
  CONSTRAINT `fk_v2_repair_report_reservation` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`) ON DELETE SET NULL,
  CONSTRAINT `v2_repair_report_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_repair_report_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_repair_report_ibfk_3` FOREIGN KEY (`reporter_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_repair_report_ibfk_4` FOREIGN KEY (`handler_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_repair_worklog` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `report_id` bigint NOT NULL,
  `operator_id` bigint NOT NULL,
  `status` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content` varchar(2000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `image_urls` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `operator_id` (`operator_id`),
  KEY `idx_v2_repair_worklog_report_created` (`report_id`,`created_at`),
  CONSTRAINT `v2_repair_worklog_ibfk_1` FOREIGN KEY (`report_id`) REFERENCES `v2_repair_report` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_repair_worklog_ibfk_2` FOREIGN KEY (`operator_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_blackout` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `scope_type` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `scope_id` bigint NOT NULL,
  `blocked_date` date NOT NULL,
  `reason` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `created_by` bigint NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_blackout_scope_date` (`scope_type`,`scope_id`,`blocked_date`),
  KEY `created_by` (`created_by`),
  KEY `idx_v2_blackout_scope_date` (`scope_type`,`scope_id`,`blocked_date`),
  CONSTRAINT `v2_reservation_blackout_ibfk_1` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_booking_restriction` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `user_id` bigint NOT NULL,
  `college_id` bigint NOT NULL,
  `scope_type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `scope_id` bigint NOT NULL,
  `reason` varchar(1000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `penalty_case_id` bigint DEFAULT NULL,
  `overdue_id` bigint DEFAULT NULL,
  `starts_at` datetime NOT NULL,
  `ends_at` datetime DEFAULT NULL,
  `released_at` datetime DEFAULT NULL,
  `release_reason` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_booking_restriction_penalty` (`penalty_case_id`),
  UNIQUE KEY `uk_v2_booking_restriction_overdue` (`overdue_id`),
  KEY `ix_v2_reservation_booking_restriction_user_id` (`user_id`),
  KEY `ix_v2_reservation_booking_restriction_college_id` (`college_id`),
  KEY `ix_v2_reservation_booking_restriction_ends_at` (`ends_at`),
  KEY `idx_v2_booking_restriction_user_scope` (`user_id`,`college_id`,`scope_type`,`scope_id`,`ends_at`),
  CONSTRAINT `v2_reservation_booking_restriction_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_reservation_booking_restriction_ibfk_2` FOREIGN KEY (`overdue_id`) REFERENCES `v2_reservation_overdue` (`id`) ON DELETE SET NULL,
  CONSTRAINT `v2_reservation_booking_restriction_ibfk_3` FOREIGN KEY (`penalty_case_id`) REFERENCES `v2_penalty_case` (`id`) ON DELETE SET NULL,
  CONSTRAINT `v2_reservation_booking_restriction_ibfk_4` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_day` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `date` date NOT NULL,
  `slot_index` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_device_date` (`device_id`,`date`),
  KEY `reservation_id` (`reservation_id`),
  KEY `idx_v2_reservation_day_device_date` (`device_id`,`date`),
  CONSTRAINT `v2_reservation_day_ibfk_1` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_reservation_day_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_feedback` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `rating` int NOT NULL,
  `comment` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_feedback_reservation` (`reservation_id`),
  KEY `user_id` (`user_id`),
  KEY `idx_v2_feedback_device_created` (`device_id`,`created_at`),
  KEY `idx_v2_feedback_college_created` (`college_id`,`created_at`),
  CONSTRAINT `v2_reservation_feedback_ibfk_1` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_reservation_feedback_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_reservation_feedback_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_inspection` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `condition` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'NORMAL',
  `note` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `image_urls` json DEFAULT NULL,
  `checklist` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_reservation_inspection_reservation` (`reservation_id`),
  KEY `user_id` (`user_id`),
  KEY `idx_v2_reservation_inspection_device` (`device_id`,`created_at`),
  CONSTRAINT `v2_reservation_inspection_ibfk_1` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`) ON DELETE CASCADE,
  CONSTRAINT `v2_reservation_inspection_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_reservation_inspection_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_overdue` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `reservation_id` bigint NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint NOT NULL,
  `lab_id` bigint DEFAULT NULL,
  `device_id` bigint NOT NULL,
  `started_at` datetime NOT NULL,
  `grace_deadline_at` datetime NOT NULL,
  `rule_version_id` bigint DEFAULT NULL,
  `penalty_case_id` bigint DEFAULT NULL,
  `status` varchar(24) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'GRACE',
  `escalated_at` datetime DEFAULT NULL,
  `escalated_by` bigint DEFAULT NULL,
  `escalation_reason` varchar(1000) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_reservation_overdue_reservation` (`reservation_id`),
  KEY `escalated_by` (`escalated_by`),
  KEY `penalty_case_id` (`penalty_case_id`),
  KEY `rule_version_id` (`rule_version_id`),
  KEY `ix_v2_reservation_overdue_reservation_id` (`reservation_id`),
  KEY `ix_v2_reservation_overdue_user_id` (`user_id`),
  KEY `ix_v2_reservation_overdue_college_id` (`college_id`),
  KEY `ix_v2_reservation_overdue_lab_id` (`lab_id`),
  KEY `ix_v2_reservation_overdue_device_id` (`device_id`),
  KEY `ix_v2_reservation_overdue_grace_deadline_at` (`grace_deadline_at`),
  KEY `ix_v2_reservation_overdue_status` (`status`),
  KEY `idx_v2_reservation_overdue_scope_status` (`college_id`,`status`,`grace_deadline_at`),
  KEY `idx_v2_reservation_overdue_user_status` (`user_id`,`status`),
  CONSTRAINT `v2_reservation_overdue_ibfk_1` FOREIGN KEY (`college_id`) REFERENCES `college` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_2` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_3` FOREIGN KEY (`escalated_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_4` FOREIGN KEY (`lab_id`) REFERENCES `lab` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_5` FOREIGN KEY (`penalty_case_id`) REFERENCES `v2_penalty_case` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_6` FOREIGN KEY (`reservation_id`) REFERENCES `reservation` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_7` FOREIGN KEY (`rule_version_id`) REFERENCES `v2_penalty_rule_version` (`id`),
  CONSTRAINT `v2_reservation_overdue_ibfk_8` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_overdue_followup` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `overdue_id` bigint NOT NULL,
  `operator_id` bigint NOT NULL,
  `contacted_at` datetime NOT NULL,
  `result` varchar(1000) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  KEY `ix_v2_reservation_overdue_followup_overdue_id` (`overdue_id`),
  KEY `ix_v2_reservation_overdue_followup_operator_id` (`operator_id`),
  KEY `idx_v2_overdue_followup_case_time` (`overdue_id`,`contacted_at`),
  CONSTRAINT `v2_reservation_overdue_followup_ibfk_1` FOREIGN KEY (`operator_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_reservation_overdue_followup_ibfk_2` FOREIGN KEY (`overdue_id`) REFERENCES `v2_reservation_overdue` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_rule` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `scope_type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `scope_id` bigint NOT NULL DEFAULT '0',
  `user_category` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ALL',
  `max_booking_days` int DEFAULT NULL,
  `max_advance_days` int DEFAULT NULL,
  `approval_required` tinyint(1) DEFAULT NULL,
  `created_by` bigint DEFAULT NULL,
  `updated_by` bigint DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `updated_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_reservation_rule_scope_category` (`scope_type`,`scope_id`,`user_category`),
  KEY `created_by` (`created_by`),
  KEY `updated_by` (`updated_by`),
  CONSTRAINT `v2_reservation_rule_ibfk_1` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `v2_reservation_rule_ibfk_2` FOREIGN KEY (`updated_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_waitlist` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `user_id` bigint NOT NULL,
  `reservation_date` date NOT NULL,
  `purpose` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'WAITING',
  `notified_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  `purpose_category` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'OTHER',
  `project_reference` varchar(160) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_waitlist_device_date_user` (`device_id`,`reservation_date`,`user_id`),
  KEY `idx_v2_waitlist_device_date_status` (`device_id`,`reservation_date`,`status`),
  KEY `idx_v2_waitlist_user_created` (`user_id`,`created_at`),
  CONSTRAINT `v2_reservation_waitlist_ibfk_1` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`),
  CONSTRAINT `v2_reservation_waitlist_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_reservation_waitlist_offer` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `waitlist_id` bigint NOT NULL,
  `device_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `user_id` bigint NOT NULL,
  `reservation_date` date NOT NULL,
  `expires_at` datetime NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_waitlist_offer_device_day` (`device_id`,`reservation_date`),
  UNIQUE KEY `uk_v2_waitlist_offer_entry` (`waitlist_id`),
  KEY `fk_waitlist_offer_user` (`user_id`),
  KEY `idx_v2_waitlist_offer_expiry` (`expires_at`,`id`),
  KEY `ix_v2_reservation_waitlist_offer_college_id` (`college_id`),
  KEY `ix_v2_reservation_waitlist_offer_expires_at` (`expires_at`),
  CONSTRAINT `fk_waitlist_offer_device` FOREIGN KEY (`device_id`) REFERENCES `device` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_waitlist_offer_entry` FOREIGN KEY (`waitlist_id`) REFERENCES `v2_reservation_waitlist` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_waitlist_offer_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_upload_asset` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `asset_token` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` bigint NOT NULL,
  `college_id` bigint DEFAULT NULL,
  `original_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `size_bytes` int NOT NULL,
  `storage_path` varchar(500) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NOT NULL DEFAULT (now()),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_upload_asset_token` (`asset_token`),
  KEY `idx_v2_upload_asset_user_created` (`user_id`,`created_at`),
  KEY `idx_v2_upload_asset_college` (`college_id`),
  CONSTRAINT `v2_upload_asset_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `v2_upload_quota_bucket` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `scope_type` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL,
  `scope_id` bigint NOT NULL DEFAULT '0',
  `used_bytes` bigint NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_v2_upload_quota_scope` (`scope_type`,`scope_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS=1;
INSERT INTO `sys_role` VALUES (1,'STUDENT','学生',1),(2,'LAB_ADMIN','实验室管理员',1),(3,'SYS_ADMIN','系统管理员',1);
INSERT INTO `sys_permission` VALUES (1,'dashboard:read','查看仪表盘','dashboard','查看当前角色范围内的运营概览'),(2,'device:read','查看设备','device','浏览授权学院范围内的设备'),(3,'device:manage','管理设备','device','新增、编辑和维护设备档案'),(4,'device:documents:manage','管理设备文档','device','上传和归档设备文档'),(5,'reservation:create','创建预约','reservation','提交设备预约申请'),(6,'reservation:read:own','查看个人预约','reservation','查看本人预约'),(7,'reservation:read:scope','查看范围内预约','reservation','查看所负责范围的预约'),(8,'reservation:cancel','取消预约','reservation','取消本人可取消的预约'),(9,'reservation:check-in','预约签到','reservation','为本人预约签到'),(10,'reservation:return','提交归还','reservation','为本人预约提交归还'),(11,'reservation:approve','审批预约','reservation','审批所负责范围内的预约'),(12,'reservation:handover','办理设备交接','reservation','办理领用交接'),(13,'reservation:accept-return','验收设备归还','reservation','验收所负责范围内的设备归还'),(14,'notification:read:own','查看个人通知','notification','查看本人通知'),(15,'repair:create','提交报修','repair','提交设备故障报修'),(16,'repair:read:own','查看个人报修','repair','查看本人报修工单'),(17,'repair:read:scope','查看范围内报修','repair','查看所负责范围内的报修'),(18,'repair:handle','处理报修','repair','受理并处理所负责范围内的报修'),(19,'repair:confirm','确认报修结果','repair','确认本人报修的处理结果'),(20,'report:read','查看运营报表','report','查看授权范围内的统计报表'),(21,'reservation-rule:manage','管理预约规则','reservation','维护授权范围内的预约规则'),(22,'maintenance:manage','管理设备维护','maintenance','维护校准计划和维护记录'),(23,'feedback:create','提交设备评价','feedback','评价本人已完成的预约'),(24,'feedback:read:own','查看个人评价','feedback','查看本人提交的设备评价'),(25,'feedback:read:scope','查看范围内评价','feedback','查看所负责范围内的评价'),(26,'organization:manage','管理组织','organization','管理学院、实验室及负责人'),(27,'organization:read','查看组织','organization','查看授权范围内的学院和实验室'),(28,'user:manage','管理用户','user','管理系统账号和角色分配'),(29,'rbac:manage','管理角色权限','rbac','配置角色和角色权限'),(30,'ai:use','使用 AI 工作台','ai','使用当前账号权限范围内的 AI 功能'),(31,'ai:knowledge:manage','管理知识库','ai','维护授权范围内的知识库'),(32,'ai:usage:read:scope','查看 AI 用量','ai','查看本人或授权范围内的 AI 用量');
INSERT INTO `sys_role_permission` VALUES (1,1),(2,1),(3,1),(1,2),(2,2),(3,2),(2,3),(3,3),(2,4),(3,4),(1,5),(3,5),(1,6),(3,6),(2,7),(3,7),(1,8),(3,8),(1,9),(3,9),(1,10),(3,10),(2,11),(3,11),(2,12),(3,12),(2,13),(3,13),(1,14),(2,14),(3,14),(1,15),(3,15),(1,16),(3,16),(2,17),(3,17),(2,18),(3,18),(1,19),(3,19),(2,20),(3,20),(2,21),(3,21),(2,22),(3,22),(1,23),(3,23),(1,24),(3,24),(2,25),(3,25),(3,26),(2,27),(3,27),(3,28),(3,29),(1,30),(2,30),(3,30),(2,31),(3,31),(2,32),(3,32);
INSERT INTO `college` VALUES (1,'LEGACY','待分配学院',0,NULL,'2026-10-13 08:03:22','2026-10-13 08:03:22'),(2,'CS','计算机学院',1,NULL,'2026-10-13 08:03:23','2026-10-13 08:03:23'),(3,'EE','电气学院',1,NULL,'2026-10-13 08:03:23','2026-10-13 08:03:23'),(4,'EIE','电子信息学院',1,NULL,'2026-10-13 08:03:23','2026-10-13 08:03:23');
INSERT INTO `v2_authz_version` VALUES (1,1,'2026-10-13 08:03:40');
