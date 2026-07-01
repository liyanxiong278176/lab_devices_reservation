-- V1__init_schema.sql
CREATE TABLE sys_user (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  password VARCHAR(100) NOT NULL,
  real_name VARCHAR(50),
  phone VARCHAR(20), email VARCHAR(100),
  user_type VARCHAR(20) DEFAULT 'STUDENT',
  dept_name VARCHAR(100),
  status TINYINT DEFAULT 1 COMMENT '0禁用 1正常',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_role (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  role_code VARCHAR(50) NOT NULL UNIQUE,
  role_name VARCHAR(50) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_user_role (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, role_id BIGINT NOT NULL,
  UNIQUE KEY uk_user_role (user_id, role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_permission (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  perm_code VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(100), type VARCHAR(20), parent_id BIGINT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_role_permission (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  role_id BIGINT NOT NULL, permission_id BIGINT NOT NULL,
  UNIQUE KEY uk_role_perm (role_id, permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE lab (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, location VARCHAR(200),
  manager_id BIGINT, description VARCHAR(500),
  status TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE device_category (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, parent_id BIGINT DEFAULT 0, sort INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE device (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL, category_id BIGINT, lab_id BIGINT,
  brand VARCHAR(100), model VARCHAR(100), specs VARCHAR(500), image_url VARCHAR(500),
  status VARCHAR(20) DEFAULT 'IDLE' COMMENT 'IDLE/IN_USE/MAINTENANCE',
  need_approval TINYINT DEFAULT 0,
  max_reservation_hours DECIMAL(5,2) DEFAULT 8.00,
  price_per_hour DECIMAL(10,2) DEFAULT 0.00,
  tags JSON, description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_lab (lab_id), KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reservation (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, device_id BIGINT NOT NULL,
  purpose VARCHAR(500),
  start_time DATETIME NOT NULL, end_time DATETIME NOT NULL,
  slot_count INT NOT NULL,
  status VARCHAR(20) NOT NULL COMMENT 'PENDING/APPROVED/IN_USE/COMPLETED/REJECTED/CANCELLED/VIOLATED/NO_SHOW',
  approver_id BIGINT, approved_at DATETIME, reject_reason VARCHAR(500),
  check_in_at DATETIME, check_out_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_user_status (user_id, status),
  KEY idx_device_status (device_id, status),
  KEY idx_status_start (status, start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE reservation_item (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  reservation_id BIGINT NOT NULL,
  device_id BIGINT NOT NULL,
  date DATE NOT NULL,
  slot_index INT NOT NULL,
  UNIQUE KEY uk_device_date_slot (device_id, date, slot_index) COMMENT '硬防超约',
  KEY idx_reservation (reservation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE repair_report (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  device_id BIGINT NOT NULL, reporter_id BIGINT NOT NULL,
  title VARCHAR(200), description TEXT, image_urls JSON,
  status VARCHAR(20) DEFAULT 'PENDING' COMMENT 'PENDING/PROCESSING/RESOLVED/REJECTED',
  handler_id BIGINT, resolution_note VARCHAR(500),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  resolved_at DATETIME,
  KEY idx_device (device_id), KEY idx_reporter (reporter_id), KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE notification (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT NOT NULL, type VARCHAR(50),
  title VARCHAR(200), content VARCHAR(1000),
  related_id BIGINT, related_type VARCHAR(50),
  is_read TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user_read (user_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE operation_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT, username VARCHAR(64),
  action VARCHAR(200), method VARCHAR(200), params TEXT,
  ip VARCHAR(50), cost_ms BIGINT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user (user_id), KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
