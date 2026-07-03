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

@Slf4j @Component @RequiredArgsConstructor
public class NotificationConsumer {
    private final NotificationService notificationService;
    private final StringRedisTemplate redisTemplate;
    @Value("${lab.mq.idempotent-ttl-hours:24}") private long idempotentTtlHours;

    @RabbitListener(queues = RabbitMQConfig.NOTIFY_QUEUE)
    public void onMessage(NotificationMessage msg) {
        String key = "mq:notify:" + msg.getMsgId();
        Boolean first = redisTemplate.opsForValue().setIfAbsent(key, "1", Duration.ofHours(idempotentTtlHours));
        if (Boolean.FALSE.equals(first)) {
            log.info("duplicate notify message skipped, msgId={}", msg.getMsgId());
            return;
        }
        notificationService.notify(msg.getUserId(), msg.getType(), msg.getTitle(), msg.getContent(), msg.getRelatedId(), msg.getRelatedType());
    }
}
