package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import java.time.Duration;

/**
 * 延迟队列集成测试（规格 §4.6）：连本地 compose rabbitmq(localhost:5672)。
 * 发短 TTL(2s) 消息到 timeout.queue → 死信路由到 cancel.queue → 断言收到。证明 TTL+DLX 链路通。
 */
@SpringBootTest
class ReservationDelayQueueIT {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    // 抑制真 consumer：否则消息死信到 cancel.queue 时会被 ReservationTimeoutConsumer
    // 抢先消费（非本测试的预约 id），测试 receive 拿不到。
    @org.springframework.boot.test.mock.mockito.MockBean
    ReservationTimeoutConsumer timeoutConsumer;

    @Test
    void short_ttl_message_deadletters_to_cancel_queue() {
        String payload = "it-test-" + System.nanoTime();
        MessagePostProcessor mpp = m -> {
            m.getMessageProperties().setExpiration("2000");
            return m;
        };
        // (Object) cast 消除 RabbitTemplate 3-arg convertAndSend 重载歧义（与 producer 同因）
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, (Object) payload, mpp);

        // awaitility 替代手轮询 40× 循环：最多等 8s，每 200ms 检查一次
        // 不只断言非空：cancel.queue 是 durable，可能残留前次/后端运行遗留的旧消息 → 假阳性。
        // 校验 body 含本次唯一 payload，证明确实是"刚发的这条"被死信路由过来。
        await().atMost(Duration.ofSeconds(8)).pollInterval(Duration.ofMillis(200)).untilAsserted(() -> {
            Message received = rabbitTemplate.receive(RabbitMQConfig.CANCEL_QUEUE, 500);
            assertThat(received).as("2s TTL 消息应死信到 cancel.queue").isNotNull();
            String body = new String(received.getBody(), StandardCharsets.UTF_8);
            assertThat(body).as("死信消息体应为本次发送的 payload").contains(payload);
        });
    }
}
