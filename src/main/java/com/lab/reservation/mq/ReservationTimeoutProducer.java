package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.MessagePostProcessor;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.Duration;
import java.time.LocalDateTime;

/**
 * 延迟取消生产者（规格 §4.3）。审批通过时调用，发延迟消息到 timeout 队列（消息级 TTL）。
 * TTL = 预约开始时间 - now + 宽限分钟；到期后死信路由到 cancel.queue。
 *
 * <p>事务后投递（与 NotificationProducer 同模式）：审批事务提交后才发，避免「审批回滚但超时消息已发」。
 *
 * <p>队头阻塞取舍：消息级 TTL 存在队头阻塞（队首未过期则其后消息即便过期也不出队）。
 * 预约场景按审批时间近似有序、TTL 相近，影响可控（详见 spec §4.4）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTimeoutProducer {

    private final RabbitTemplate rabbitTemplate;

    @Value("${lab.reservation.signin-grace-minutes:30}")
    private long graceMinutes;

    public void sendTimeout(Long reservationId, LocalDateTime startTime) {
        long ttlMillis = Math.max(0,
                Duration.between(LocalDateTime.now(), startTime).toMillis() + graceMinutes * 60_000);
        String payload = String.valueOf(reservationId);
        MessagePostProcessor mpp = msg -> {
            msg.getMessageProperties().setExpiration(String.valueOf(ttlMillis));
            return msg;
        };

        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSend(payload, mpp, reservationId, ttlMillis);
                }
            });
        } else {
            doSend(payload, mpp, reservationId, ttlMillis);
        }
    }

    private void doSend(String payload, MessagePostProcessor mpp, Long id, long ttlMillis) {
        // 3-arg convertAndSend(routingKey, message, postProcessor): 默认 exchange("") + 队列名作 routingKey
        // → 路由到同名 timeout.queue。切勿用 4-arg（会把队列名误当 exchange，消息不可路由）。
        // (Object) cast 消除与 convertAndSend(exchange,routingKey,message) 的重载歧义。
        rabbitTemplate.convertAndSend(RabbitMQConfig.TIMEOUT_QUEUE, (Object) payload, mpp);
        log.debug("reservation timeout message sent: id={} ttlMs={}", id, ttlMillis);
    }
}
