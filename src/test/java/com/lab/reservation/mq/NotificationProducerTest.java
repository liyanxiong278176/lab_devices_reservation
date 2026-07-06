package com.lab.reservation.mq;

import com.lab.reservation.task.NotificationDispatcher;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * 锁定 producer 契约：构造 {@link NotificationMessage}（带 UUID msgId）并调 dispatcher.dispatch。
 *
 * <p>替代原 RabbitTemplate 验证：原方案 verify rabbit.convertAndSend(exchange, routingKey, msg)；
 * 新方案 verify dispatcher.dispatch(msg)。语义不变：构造消息 + 投递。
 */
class NotificationProducerTest {

    @Test
    void notify_dispatches_message_with_msgId_to_dispatcher() {
        NotificationDispatcher dispatcher = mock(NotificationDispatcher.class);
        NotificationProducer producer = new NotificationProducer(dispatcher);
        producer.notify(25L, "APPROVAL", "预约已通过", "内容", 12L, "RESERVATION");

        ArgumentCaptor<NotificationMessage> cap = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(dispatcher, times(1)).dispatch(cap.capture());
        NotificationMessage sent = cap.getValue();
        assertThat(sent.getUserId()).isEqualTo(25L);
        assertThat(sent.getType()).isEqualTo("APPROVAL");
        assertThat(sent.getTitle()).isEqualTo("预约已通过");
        assertThat(sent.getContent()).isEqualTo("内容");
        assertThat(sent.getRelatedId()).isEqualTo(12L);
        assertThat(sent.getRelatedType()).isEqualTo("RESERVATION");
        assertThat(sent.getMsgId()).isNotBlank();
    }

    @Test
    void notify_generates_unique_msgId_for_idempotency() {
        NotificationDispatcher dispatcher = mock(NotificationDispatcher.class);
        NotificationProducer producer = new NotificationProducer(dispatcher);
        producer.notify(1L, "T", "t", "c", 1L, "R");
        producer.notify(1L, "T", "t", "c", 1L, "R");

        ArgumentCaptor<NotificationMessage> cap = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(dispatcher, times(2)).dispatch(cap.capture());
        var ids = cap.getAllValues().stream().map(NotificationMessage::getMsgId).toList();
        assertThat(ids.get(0)).isNotEqualTo(ids.get(1));
    }

    @Test
    void notify_within_transaction_defers_dispatch_until_afterCommit() {
        NotificationDispatcher dispatcher = mock(NotificationDispatcher.class);
        NotificationProducer producer = new NotificationProducer(dispatcher);

        TransactionSynchronizationManager.initSynchronization();
        try {
            producer.notify(9L, "APPROVAL", "已通过", "内容", 3L, "RESERVATION");

            // 同步阶段不应派发：事务尚未提交，dispatch 被注册到 afterCommit 回调
            verify(dispatcher, never()).dispatch(any(NotificationMessage.class));

            // 手动触发注册的 afterCommit，模拟事务提交
            List<TransactionSynchronization> syncs = TransactionSynchronizationManager.getSynchronizations();
            assertThat(syncs).hasSize(1);
            syncs.get(0).afterCommit();

            // afterCommit 之后才真正派发
            verify(dispatcher, times(1)).dispatch(any(NotificationMessage.class));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }
}
