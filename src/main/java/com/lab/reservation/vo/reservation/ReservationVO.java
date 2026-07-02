package com.lab.reservation.vo.reservation;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 预约返回视图。
 */
@Data
public class ReservationVO {
    private Long id;
    private Long userId;
    private Long deviceId;
    private String purpose;
    private LocalDateTime startTime;
    private LocalDateTime endTime;
    private Integer slotCount;
    private String status;
    private LocalDateTime createdAt;
}
