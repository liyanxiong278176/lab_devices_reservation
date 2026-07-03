package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import java.time.LocalDateTime;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ReservationTimeoutProducerTest {
    @Test
    void sendTimeout_sends_to_timeout_queue_with_expiration_3arg() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(rabbit);
        producer.sendTimeout(42L, LocalDateTime.now().plusMinutes(30));
        // 3-arg convertAndSend(routingKey, message, postProcessor): default exchange + queue name routingKey
        // (Object) cast 消除与 convertAndSend(exchange,routingKey,message) 的重载歧义
        verify(rabbit).convertAndSend(eq("reservation.timeout.queue"), (Object) eq("timeout:42"), any(MessagePostProcessor.class));
    }
}
