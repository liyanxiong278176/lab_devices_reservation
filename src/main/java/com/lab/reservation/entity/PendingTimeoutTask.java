package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 本地延迟任务实体（替代 RabbitMQ TTL+DLX）。
 *
 * <p>审批通过时 Producer 写入一行 {@code execute_at = startTime + graceMinutes}；
 * {@code LocalTimeoutScheduler} 每 5s 扫描 {@code status='PENDING' AND execute_at <= NOW()}
 * 的行执行（调 {@code reservationService.markTimeoutCancelled} + 通知）。
 *
 * <p>DB 是真值源：重启 / 宕机后扫描器仍能从表中捡起错过的任务。
 */
@Data
@TableName("pending_timeout_task")
public class PendingTimeoutTask {

    public enum Status {
        PENDING, DONE, FAILED
    }

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long reservationId;

    private LocalDateTime executeAt;

    private String status;

    private Integer attempts;

    private String lastError;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
