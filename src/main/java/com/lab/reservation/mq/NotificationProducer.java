package com.lab.reservation.mq;

import com.lab.reservation.task.NotificationDispatcher;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.UUID;

/**
 * 通知消息生产者。规格 §4.3。
 *
 * <p>替代原 RabbitMQ 方案：构造 {@link NotificationMessage}（含 UUID {@code msgId} 幂等键）
 * 交给 {@link NotificationDispatcher} 异步派发，不再走 broker。
 *
 * <p><b>事务后投递</b>：当调用方处于事务中时，构造+派发动作通过
 * {@link TransactionSynchronizationManager} 注册到 {@link TransactionSynchronization#afterCommit()}
 * —— 只有事务成功提交后才真正派发。这样避免了"事务回滚但通知已发"的幻觉通知。
 * 无事务上下文时立即派发。
 *
 * <p>每条消息带 UUID {@code msgId}，供 {@link NotificationDispatcher} 做幂等去重。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationProducer {

    private final NotificationDispatcher notificationDispatcher;

    /**
     * 发送一条通知。事务活跃时延迟到 afterCommit 执行。
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
                    doDispatch(msg);
                }
            });
        } else {
            doDispatch(msg);
        }
    }

    private void doDispatch(NotificationMessage msg) {
        notificationDispatcher.dispatch(msg);
        log.debug("notify message dispatched: userId={} type={} msgId={}", msg.getUserId(), msg.getType(), msg.getMsgId());
    }
}
