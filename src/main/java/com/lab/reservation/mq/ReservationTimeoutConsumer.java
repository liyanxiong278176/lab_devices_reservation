package com.lab.reservation.mq;

import com.lab.reservation.config.RabbitMQConfig;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * 延迟取消消费者（规格 §4.3）。死信到期后从 cancel.queue 收到 reservationId（纯数字字符串）。
 * 判断：状态仍 APPROVED（签到会流转到 IN_USE，故未签到 = 仍 APPROVED）→ 标记 TIMEOUT 取消 + 通知。
 * 已签到(IN_USE)/已取消/已完成 → 幂等跳过。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTimeoutConsumer {

    private final ReservationMapper reservationMapper;
    private final ReservationService reservationService;
    private final NotificationProducer notificationProducer;

    @RabbitListener(queues = RabbitMQConfig.CANCEL_QUEUE)
    public void onTimeout(String reservationId) {
        Long id;
        try {
            id = Long.valueOf(reservationId.trim());
        } catch (NumberFormatException e) {
            // 防御异常/恶意 payload：直接 drop，避免无限重试耗尽 broker 资源
            log.warn("timeout: malformed reservationId payload '{}', dropping", reservationId);
            return;
        }
        Reservation r = reservationMapper.selectById(id);
        if (r == null) {
            log.warn("timeout: reservation {} not found", id);
            return;
        }
        if (!ReservationStatus.APPROVED.name().equals(r.getStatus())) {
            log.debug("timeout: reservation {} status={}, skip", id, r.getStatus());
            return;
        }
        reservationService.markTimeoutCancelled(id);
        // 已知取舍（答辩点）：markTimeoutCancelled 提交后、notify 调用前若 broker down → 消息重投时
        // 状态已变 CANCELLED 触发上面的 skip → 实时推送丢失。DB 行是最终真相（用户列表可见取消状态）；
        // 完美解需事务性 outbox，本期作为已知取舍（详见 spec §4.4）。
        notificationProducer.notify(r.getUserId(), "RESERVATION", "预约超时已自动取消",
                "预约 " + id + " 超时未签到，已自动取消", id, "RESERVATION");
        log.debug("reservation {} auto-cancelled by timeout", id);
    }
}
