package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 延迟队列集成测试（规格 §4.6）：连本地 compose rabbitmq(localhost:5672)。
 * 发短 TTL(2s) 消息到 timeout.queue → 死信路由到 cancel.queue → 断言收到。证明 TTL+DLX 链路通。
 */
@SpringBootTest
class ReservationDelayQueueIT {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    // 抑制真 consumer：否则消息死信到 cancel.queue 时会被 ReservationTimeoutConsumer
    // 抢先消费（payload "it-test-..." 非数字 → NumberFormatException），测试 receive 拿不到。
    @org.springframework.boot.test.mock.mockito.MockBean
    ReservationTimeoutConsumer timeoutConsumer;

    @Test
    void short_ttl_message_deadletters_to_cancel_queue() throws Exception {
        String payload = "it-test-" + System.nanoTime();
        MessagePostProcessor mpp = m -> {
            m.getMessageProperties().setExpiration("2000");
            return m;
        };
        // (Object) cast 消除 RabbitTemplate 3-arg convertAndSend 重载歧义（与 producer 同因）
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, (Object) payload, mpp);

        Message received = null;
        for (int i = 0; i < 40; i++) {
            received = rabbitTemplate.receive(RabbitMQConfig.CANCEL_QUEUE, 500);
            if (received != null) break;
            Thread.sleep(200);
        }
        // 不只断言非空：cancel.queue 是 durable，可能残留前次/后端运行遗留的旧消息 → 假阳性。
        // 校验 body 含本次唯一 payload，证明确实是“刚发的这条”被死信路由过来。
        assertThat(received).as("2s TTL 消息应死信到 cancel.queue").isNotNull();
        String body = new String(received.getBody(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(body).as("死信消息体应为本次发送的 payload").contains(payload);
    }
}
