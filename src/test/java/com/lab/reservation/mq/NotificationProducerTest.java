package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
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
        org.mockito.ArgumentCaptor<NotificationMessage> cap = org.mockito.ArgumentCaptor.forClass(NotificationMessage.class);
        verify(rabbit, times(2)).convertAndSend(anyString(), anyString(), cap.capture());
        var ids = cap.getAllValues().stream().map(NotificationMessage::getMsgId).toList();
        org.assertj.core.api.Assertions.assertThat(ids.get(0)).isNotEqualTo(ids.get(1));
    }
}
