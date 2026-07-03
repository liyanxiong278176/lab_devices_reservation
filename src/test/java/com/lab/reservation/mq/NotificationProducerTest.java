package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class NotificationProducerTest {
    @Test
    void notify_sends_message_with_msgId_to_notify_exchange() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        NotificationProducer producer = new NotificationProducer(rabbit);
        producer.notify(25L, "APPROVAL", "预约已通过", "内容", 12L, "RESERVATION");
        verify(rabbit).convertAndSend(eq("notify.exchange"), eq("notify"), any(NotificationMessage.class));
    }

    @Test
    void notify_generates_unique_msgId_for_idempotency() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        NotificationProducer producer = new NotificationProducer(rabbit);
        producer.notify(1L, "T", "t", "c", 1L, "R");
        producer.notify(1L, "T", "t", "c", 1L, "R");
        ArgumentCaptor<NotificationMessage> cap = ArgumentCaptor.forClass(NotificationMessage.class);
        verify(rabbit, times(2)).convertAndSend(anyString(), anyString(), cap.capture());
        var ids = cap.getAllValues().stream().map(NotificationMessage::getMsgId).toList();
        assertThat(ids.get(0)).isNotEqualTo(ids.get(1));
    }

    @Test
    void notify_within_transaction_defers_send_until_afterCommit() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        NotificationProducer producer = new NotificationProducer(rabbit);

        TransactionSynchronizationManager.initSynchronization();
        try {
            producer.notify(9L, "APPROVAL", "已通过", "内容", 3L, "RESERVATION");

            // 同步阶段不应发送：事务尚未提交，投递被注册到 afterCommit 回调
            verify(rabbit, never()).convertAndSend(anyString(), anyString(), any(NotificationMessage.class));

            // 手动触发注册的 afterCommit，模拟事务提交
            List<TransactionSynchronization> syncs = TransactionSynchronizationManager.getSynchronizations();
            assertThat(syncs).hasSize(1);
            syncs.get(0).afterCommit();

            // afterCommit 之后才真正投递
            verify(rabbit, times(1)).convertAndSend(eq("notify.exchange"), eq("notify"), any(NotificationMessage.class));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }
}
