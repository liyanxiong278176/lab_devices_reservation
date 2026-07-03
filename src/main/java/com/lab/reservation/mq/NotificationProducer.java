package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.UUID;

/**
 * 通知消息生产者。规格 §4.3。
 *
 * <p><b>事务后投递</b>：当调用方处于事务中时，投递动作通过
 * {@link TransactionSynchronizationManager} 注册到 {@link TransactionSynchronization#afterCommit()}
 * —— 只有事务成功提交后才真正发 MQ。这样避免了「先发消息、后事务回滚」导致的
 * 幻觉通知（消费者收到一条 DB 里根本不存在的业务事件）。无事务上下文时立即投递。
 *
 * <p>每条消息带 UUID {@code msgId}，供 {@link NotificationConsumer} 做幂等去重。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationProducer {

    private final RabbitTemplate rabbitTemplate;

    /**
     * 发送一条通知消息。事务活跃时延迟到 afterCommit 执行。
     *
     * @param userId      接收人
     * @param type        类型（RESERVATION / APPROVAL / REPAIR）
     * @param title       标题
     * @param content     正文
     * @param relatedId   关联业务 id
     * @param relatedType 关联类型（RESERVATION / REPAIR）
     */
    public void notify(Long userId, String type, String title, String content, Long relatedId, String relatedType) {
        NotificationMessage msg = new NotificationMessage(
                UUID.randomUUID().toString(), userId, type, title, content, relatedId, relatedType);
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSend(msg);
                }
            });
        } else {
            doSend(msg);
        }
    }

    private void doSend(NotificationMessage msg) {
        rabbitTemplate.convertAndSend(RabbitMQConfig.NOTIFY_EXCHANGE, RabbitMQConfig.NOTIFY_ROUTING_KEY, msg);
        log.debug("notify message sent: userId={} type={} msgId={}", msg.getUserId(), msg.getType(), msg.getMsgId());
    }
}
