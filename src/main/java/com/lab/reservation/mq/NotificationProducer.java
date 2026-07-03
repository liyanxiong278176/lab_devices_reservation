package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.UUID;

@Slf4j @Component @RequiredArgsConstructor
public class NotificationProducer {
    private final RabbitTemplate rabbitTemplate;

    public void notify(Long userId, String type, String title, String content, Long relatedId, String relatedType) {
        NotificationMessage msg = new NotificationMessage(UUID.randomUUID().toString(), userId, type, title, content, relatedId, relatedType);
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { doSend(msg); }
            });
        } else { doSend(msg); }
    }
    private void doSend(NotificationMessage msg) {
        rabbitTemplate.convertAndSend(RabbitMQConfig.NOTIFY_EXCHANGE, RabbitMQConfig.NOTIFY_ROUTING_KEY, msg);
        log.debug("notify message sent: userId={} type={} msgId={}", msg.getUserId(), msg.getType(), msg.getMsgId());
    }
}
