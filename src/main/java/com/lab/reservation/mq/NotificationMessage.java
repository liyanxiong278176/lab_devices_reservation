package com.lab.reservation.mq;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 通知消息载体（Producer → Consumer 间的 AMQP 消息体）。
 *
 * <p>{@link #msgId} 为幂等键：Producer 用 UUID 生成，Consumer 据其在 Redis 做 SET NX 去重，
 * 保证同一条业务事件即便被 broker 重投也只落库一次。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class NotificationMessage {

    /** 幂等键（UUID），用于 Consumer 侧 Redis 去重。 */
    private String msgId;

    /** 接收人 user_id。 */
    private Long userId;

    /** 通知类型（RESERVATION / APPROVAL / REPAIR）。 */
    private String type;

    /** 标题。 */
    private String title;

    /** 正文。 */
    private String content;

    /** 关联业务 id（预约 id / 报修 id）。 */
    private Long relatedId;

    /** 关联类型（RESERVATION / REPAIR）。 */
    private String relatedType;
}
