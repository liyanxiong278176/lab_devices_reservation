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
 * 延迟取消消费者（规格 §4.3）。死信到期后从 cancel.queue 收到 reservationId。
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
        Long id = Long.valueOf(reservationId.trim());
        Reservation r = reservationMapper.selectById(id);
        if (r == null) {
            log.warn("timeout: reservation {} not found", id);
            return;
        }
        if (!ReservationStatus.APPROVED.name().equals(r.getStatus())) {
            log.info("timeout: reservation {} status={}, skip", id, r.getStatus());
            return;
        }
        reservationService.markTimeoutCancelled(id);
        notificationProducer.notify(r.getUserId(), "RESERVATION", "预约超时已自动取消",
                "预约 " + id + " 超时未签到，已自动取消", id, "RESERVATION");
        log.info("reservation {} auto-cancelled by timeout", id);
    }
}
