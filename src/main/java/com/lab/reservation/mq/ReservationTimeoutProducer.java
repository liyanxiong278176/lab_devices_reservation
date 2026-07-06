package com.lab.reservation.mq;

import com.lab.reservation.entity.PendingTimeoutTask;
import com.lab.reservation.mapper.PendingTimeoutTaskMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 延迟取消生产者（规格 §4.3）。审批通过时调用，落库一行 {@code pending_timeout_task}。
 * 由 {@code LocalTimeoutScheduler} 周期扫描执行（替代原 RabbitMQ TTL+DLX）。
 *
 * <p><b>事务后落库</b>：与原 NotificationProducer 同模式 —— 审批事务提交后才入库，
 * 避免"审批回滚但超时任务已建"。无事务上下文时立即落库。
 *
 * <p>execute_at = 预约开始时间 + graceMinutes（默认 30 分钟签到宽限期）。
 * 调度器扫描到点时调 {@code reservationService.markTimeoutCancelled} 取消预约 + 通知。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTimeoutProducer {

    private final PendingTimeoutTaskMapper taskMapper;

    @Value("${lab.reservation.signin-grace-minutes:30}")
    private long graceMinutes;

    /**
     * 入库一个超时取消任务。事务活跃时延迟到 afterCommit 落库。
     */
    public void sendTimeout(Long reservationId, LocalDateTime startTime) {
        long delayMs = Math.max(0,
                Duration.between(LocalDateTime.now(), startTime).toMillis() + graceMinutes * 60_000L);
        LocalDateTime executeAt = LocalDateTime.now().plus(Duration.ofMillis(delayMs));

        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doInsert(reservationId, executeAt);
                }
            });
        } else {
            doInsert(reservationId, executeAt);
        }
    }

    private void doInsert(Long reservationId, LocalDateTime executeAt) {
        PendingTimeoutTask t = new PendingTimeoutTask();
        t.setReservationId(reservationId);
        t.setExecuteAt(executeAt);
        t.setStatus(PendingTimeoutTask.Status.PENDING.name());
        t.setAttempts(0);
        taskMapper.insert(t);
        log.debug("timeout task inserted: id={} reservationId={} executeAt={}",
                t.getId(), reservationId, executeAt);
    }
}
