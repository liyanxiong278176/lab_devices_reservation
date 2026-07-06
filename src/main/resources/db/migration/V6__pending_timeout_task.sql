-- 本地表：替代 RabbitMQ TTL+DLX 实现的"延迟任务"持久化
--
-- 用途：审批通过后发延迟任务（签到宽限期到 → 自动取消预约）。
-- 替代方案：之前用 reservation.timeout.queue(TTL)+ 死信路由到 cancel.queue。
-- 当前方案：DB 落表 + @Scheduled 扫描执行。重启不丢任务，DB 是单一真值源。
--
-- 字段：
--   id              PK
--   reservation_id  业务 id（无 FK：即使 reservation 行被删，task 仍可被扫描 + 幂等处理）
--   execute_at      计划执行时间（宽限期到点）
--   status          PENDING / DONE / FAILED
--   attempts        已尝试次数（失败时 +1，> 5 标 FAILED 不再重试）
--   last_error      最近一次失败堆栈摘要（仅失败时填）
--   created_at      入库时间
--   updated_at      状态变更时间
--
-- 索引：idx_execute_at_status 给扫描查询（WHERE status='PENDING' AND execute_at <= NOW()）。
--       idx_reservation_id 排查/重放时定位。
CREATE TABLE pending_timeout_task (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    reservation_id  BIGINT       NOT NULL,
    execute_at      DATETIME(3)  NOT NULL,
    status          VARCHAR(16)  NOT NULL DEFAULT 'PENDING',
    attempts        INT          NOT NULL DEFAULT 0,
    last_error      VARCHAR(500) NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    KEY idx_execute_at_status (status, execute_at),
    KEY idx_reservation_id (reservation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='本地延迟任务表：替代 RabbitMQ TTL+DLX';
