package com.lab.reservation.mq;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 锁定 producer payload 契约：纯数字 reservationId（无前缀）。
 * 回归 C1：原 "timeout:42" 前缀与 consumer 的 Long.valueOf 不兼容 → NumberFormatException → 消息丢弃。
 */
class ReservationTimeoutProducerTest {
    @Test
    void sendTimeout_sends_pure_numeric_payload_to_timeout_queue() {
        RabbitTemplate rabbit = mock(RabbitTemplate.class);
        ReservationTimeoutProducer producer = new ReservationTimeoutProducer(rabbit);
        producer.sendTimeout(42L, LocalDateTime.now().plusMinutes(30));

        // 3-arg convertAndSend(routingKey, message, postProcessor): default exchange + queue name routingKey
        // (Object) cast 消除与 convertAndSend(exchange,routingKey,message) 的重载歧义
        ArgumentCaptor<Object> payloadCaptor = ArgumentCaptor.forClass(Object.class);
        verify(rabbit).convertAndSend(eq("reservation.timeout.queue"), payloadCaptor.capture(),
                any(MessagePostProcessor.class));

        // 契约：纯数字，不带任何前缀 —— consumer 侧 Long.valueOf 必须能解析
        String captured = (String) payloadCaptor.getValue();
        assertThat(captured).isEqualTo("42");
        assertThat(captured).matches("\\d+");
    }
}
