package com.lab.reservation.task;

import com.lab.reservation.mq.NotificationMessage;
import com.lab.reservation.service.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * 通知异步派发器。替代原 {@code NotificationConsumer}（RabbitMQ 消费者）。
 *
 * <p>Producer（{@code NotificationProducer.notify}）在事务提交后构造 {@link NotificationMessage}
 * 并调 {@link #dispatch}。本 Bean 是独立 Spring 组件 → {@code @Async} 通过代理在新线程跑，
 * 满足"事务回滚则不发通知"的语义。
 *
 * <p><b>Redis 幂等</b>：{@code setIfAbsent(msgId, 1, ttl)} 保证同一业务事件只落库一次。
 * 原 RabbitMQ 方案靠 broker 重投去重；现在没有 broker，幂等键主要防御以下场景：
 * <ol>
 *   <li>同一事务后 afterCommit 触发多次（极少见，但 Spring 同步器在嵌套事务里有重入风险）</li>
 *   <li>未来若启用分布式部署（多实例），跨实例重复消费</li>
 * </ol>
 *
 * <p><b>失败回退</b>：调 {@code notificationService.notify} 失败时，删幂等键重抛。
 * 异常被 {@code AsyncConfig.GlobalAsyncExceptionHandler} 兜底打 warn。
 * 与原 RabbitMQ 方案"重试 3 次 → DLQ"的取舍：单实例项目下，DB 写失败 = 整体降级，
 * 重试大概率再失败；落 warn + 用户主动查"我的通知"已足够。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class NotificationDispatcher {

    private final NotificationService notificationService;
    private final StringRedisTemplate redisTemplate;

    @Value("${lab.task.notify.idempotent-ttl-hours:24}")
    private long idempotentTtlHours;

    /**
     * 派发一条通知。在 {@code asyncDispatchExecutor} 上跑（新线程）。
     *
     * <p>幂等性：msgId 已在 Redis 占位则跳过（return）—— 重复消息直接吞掉。
     * 业务调用失败：删幂等键 + 抛异常，让全局异常处理打 warn。
     */
    @Async("asyncDispatchExecutor")
    public void dispatch(NotificationMessage msg) {
        String key = "task:notify:" + msg.getMsgId();
        Boolean first = redisTemplate.opsForValue()
                .setIfAbsent(key, "1", Duration.ofHours(idempotentTtlHours));
        if (Boolean.FALSE.equals(first)) {
            log.debug("duplicate notify message skipped, msgId={}", msg.getMsgId());
            return;
        }
        try {
            notificationService.notify(msg.getUserId(), msg.getType(), msg.getTitle(),
                    msg.getContent(), msg.getRelatedId(), msg.getRelatedType());
        } catch (RuntimeException e) {
            // 失败：删幂等键让后续重试可重新处理（虽然 @Async 不重试，但保留键语义以便未来扩展）
            redisTemplate.delete(key);
            throw e;
        }
    }
}
