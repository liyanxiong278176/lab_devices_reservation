package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import com.lab.reservation.service.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * 通知消息消费者。规格 §4.3、§4.4。
 *
 * <p><b>Redis 幂等去重</b>：处理前以 {@code msgId} 在 Redis 做 SET NX（TTL=24h）。
 * 已存在视为重复直接跳过，保证 broker 重投不产生重复通知。
 *
 * <p><b>失败回退</b>：若下游 {@link NotificationService#notify} 抛异常，先删除幂等键再抛出，
 * 使 broker 重投（受 retry 配置控制，耗尽后进 DLQ）时能重新处理，避免「键已占、处理已败」
 * 导致消息永久丢失。配合 application*.yml 的 default-requeue-rejected=false + retry，
 * 形成「重试 → 仍失败 → 死信兜底」的可靠链路。
 *
 * <p>复用现有 {@link NotificationService} 的同步 {@code notify} 落库逻辑，不改动其实现。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationConsumer {

    private final NotificationService notificationService;
    private final StringRedisTemplate redisTemplate;

    @Value("${lab.mq.idempotent-ttl-hours:24}")
    private long idempotentTtlHours;

    @RabbitListener(queues = RabbitMQConfig.NOTIFY_QUEUE)
    public void onMessage(NotificationMessage msg) {
        String key = "mq:notify:" + msg.getMsgId();
        Boolean first = redisTemplate.opsForValue().setIfAbsent(key, "1", Duration.ofHours(idempotentTtlHours));
        if (Boolean.FALSE.equals(first)) {
            log.debug("duplicate notify message skipped, msgId={}", msg.getMsgId());
            return;
        }
        try {
            notificationService.notify(msg.getUserId(), msg.getType(), msg.getTitle(),
                    msg.getContent(), msg.getRelatedId(), msg.getRelatedType());
        } catch (Exception e) {
            // 处理失败：删幂等键，让 broker 重投可再次处理；抛出触发 retry，耗尽后进 DLQ
            redisTemplate.delete(key);
            throw e;
        }
    }
}
