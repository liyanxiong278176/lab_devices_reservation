package com.lab.reservation.mq;

import com.lab.reservation.entity.PendingTimeoutTask;
import com.lab.reservation.mapper.PendingTimeoutTaskMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * 锁定 producer 契约：构造 {@link PendingTimeoutTask}（含 reservationId + execute_at + status=PENDING）
 * 调 mapper.insert。
 *
 * <p>替代原 RabbitTemplate 验证：原方案 verify convertAndSend(routingKey, payload, postProcessor)；
 * 新方案 verify mapper.insert(task) + execute_at = startTime + graceMinutes。
 */
class ReservationTimeoutProducerTest {

    @Test
    void sendTimeout_inserts_task_with_execute_at_start_plus_grace() {
        PendingTimeoutTaskMapper mapper = mock(PendingTimeoutTaskMapper.class);
        // mock insert 时回填 id
        org.mockito.Mockito.doAnswer(inv -> {
            PendingTimeoutTask t = inv.getArgument(0);
            t.setId(1L);
            return 1;
        }).when(mapper).insert(any(PendingTimeoutTask.class));

        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(mapper);
        ReflectionTestUtils.setField(producer, "graceMinutes", 30L);

        LocalDateTime start = LocalDateTime.now().plusMinutes(60);  // 1h 后开始
        producer.sendTimeout(42L, start);

        ArgumentCaptor<PendingTimeoutTask> cap = ArgumentCaptor.forClass(PendingTimeoutTask.class);
        verify(mapper, times(1)).insert(cap.capture());

        PendingTimeoutTask inserted = cap.getValue();
        assertThat(inserted.getReservationId()).isEqualTo(42L);
        assertThat(inserted.getStatus()).isEqualTo(PendingTimeoutTask.Status.PENDING.name());
        assertThat(inserted.getAttempts()).isZero();
        // execute_at 应近似 = start + 30min (允许 ±5s 误差)
        LocalDateTime expected = start.plusMinutes(30);
        long diffSec = Math.abs(java.time.Duration.between(expected, inserted.getExecuteAt()).getSeconds());
        assertThat(diffSec).as("execute_at 应等于 start+grace").isLessThan(5);
    }

    @Test
    void sendTimeout_within_transaction_defers_insert_until_afterCommit() {
        PendingTimeoutTaskMapper mapper = mock(PendingTimeoutTaskMapper.class);
        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(mapper);
        ReflectionTestUtils.setField(producer, "graceMinutes", 30L);

        TransactionSynchronizationManager.initSynchronization();
        try {
            producer.sendTimeout(7L, LocalDateTime.now().plusMinutes(30));

            // 同步阶段不应落库：事务尚未提交，insert 被注册到 afterCommit 回调
            verify(mapper, never()).insert(any(PendingTimeoutTask.class));

            // 手动触发注册的 afterCommit，模拟事务提交
            List<TransactionSynchronization> syncs = TransactionSynchronizationManager.getSynchronizations();
            assertThat(syncs).hasSize(1);
            syncs.get(0).afterCommit();

            verify(mapper, times(1)).insert(any(PendingTimeoutTask.class));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void sendTimeout_with_past_startTime_uses_start_plus_grace_not_now() {
        // 业务逻辑：execute_at = max(now, start + grace)。即使用户 startTime 早于 now（罕见），
        // 也按 start + grace 走（保证"从预约开始 30 min 签到宽限"的语义，不缩成 now）。
        PendingTimeoutTaskMapper mapper = mock(PendingTimeoutTaskMapper.class);
        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(mapper);
        ReflectionTestUtils.setField(producer, "graceMinutes", 30L);

        LocalDateTime past = LocalDateTime.now().minusMinutes(10);
        producer.sendTimeout(99L, past);

        ArgumentCaptor<PendingTimeoutTask> cap = ArgumentCaptor.forClass(PendingTimeoutTask.class);
        verify(mapper).insert(cap.capture());
        // execute_at 应 = past + 30min ≈ now + 20min（允许 ±5s 误差）
        LocalDateTime expected = past.plusMinutes(30);
        long diffSec = Math.abs(java.time.Duration.between(expected, cap.getValue().getExecuteAt()).getSeconds());
        assertThat(diffSec).as("execute_at 应等于 start+grace 即 now+20min").isLessThan(5);
    }
}
