package com.lab.reservation.entity.enums;

/**
 * 预约取消来源（与 {@link ReservationStatus#CANCELLED} 配合，区分「谁取消的」）。
 * 存 String（同 ReservationStatus 模式），无 MyBatis 配置变化。
 */
public enum CancelReason {
    /** 用户主动取消。 */
    USER,
    /** 超时未签到，延迟队列自动取消。 */
    TIMEOUT
}
