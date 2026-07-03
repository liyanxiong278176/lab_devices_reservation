-- 区分取消来源：USER（用户主动）/ TIMEOUT（超时未签到自动取消）
ALTER TABLE reservation ADD COLUMN cancel_reason VARCHAR(32) NULL AFTER status;
