package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.rabbit.core.RabbitAdmin;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

/**
 * 延迟队列集成测试（规格 §4.6）：连本地 compose rabbitmq(localhost:5672)。
 * 发短 TTL(2s) 消息到 timeout.queue → 死信经 cancel.exchange 路由 → 断言收到。证明 TTL+DLX 链路通。
 *
 * <p>用独占 auto-delete 测试队列绑 cancel.exchange，而非共享 cancel.queue：
 * 运行中的后端也有 ReservationTimeoutConsumer 监听 cancel.queue，若 IT 也收 cancel.queue，
 * 真 consumer 会抢先消费（round-robin）导致 IT 超时 flake。死信经 direct exchange 路由到所有
 * 匹配绑定的队列，故独占测试队列同样能收到，且与真 consumer 隔离，测试稳定可复现。
 */
@SpringBootTest
class ReservationDelayQueueIT {

    @Autowired
    private RabbitTemplate rabbitTemplate;

    @Autowired
    private RabbitAdmin rabbitAdmin;

    @Test
    void short_ttl_message_deadletters_via_cancel_exchange() {
        // 独占测试队列绑 cancel.exchange（routingKey reservation.cancel），与真 consumer 隔离
        // 用 durable（非 autoDelete）：autoDelete 队列在 declare 的 channel 关闭且无 consumer 时会被删 → receive NOT_FOUND
        String qName = "it.cancel." + UUID.randomUUID();
        Queue testQ = QueueBuilder.durable(qName).build();
        Binding binding = BindingBuilder.bind(testQ)
                .to(new DirectExchange(RabbitMQConfig.CANCEL_EXCHANGE))
                .with(RabbitMQConfig.CANCEL_ROUTING_KEY);
        rabbitAdmin.declareQueue(testQ);
        rabbitAdmin.declareBinding(binding);

        String payload = "it-test-" + System.nanoTime();
        MessagePostProcessor mpp = m -> {
            m.getMessageProperties().setExpiration("2000");
            return m;
        };
        // (Object) cast 消除 RabbitTemplate 3-arg convertAndSend 重载歧义（与 producer 同因）
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, (Object) payload, mpp);

        try {
            // body 含本次唯一 payload，证明确实是刚发的这条被死信路由（防残留假阳性）
            await().atMost(Duration.ofSeconds(8)).pollInterval(Duration.ofMillis(200)).untilAsserted(() -> {
                Message received = rabbitTemplate.receive(qName, 500);
                assertThat(received).as("2s TTL 消息应死信经 cancel.exchange 路由到测试队列").isNotNull();
                String body = new String(received.getBody(), StandardCharsets.UTF_8);
                assertThat(body).as("死信消息体应为本次发送的 payload").contains(payload);
            });
        } finally {
            rabbitAdmin.deleteQueue(qName);
        }
    }
}
