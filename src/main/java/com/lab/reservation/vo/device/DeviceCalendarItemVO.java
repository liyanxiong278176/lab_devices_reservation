package com.lab.reservation.vo.device;

import lombok.Data;

import java.time.LocalDate;

/**
 * 设备日历单项：某天某 slot 被某个有效状态预约占用。
 */
@Data
public class DeviceCalendarItemVO {
    private LocalDate date;
    private Integer slotIndex;
    private Long reservationId;
    /** PENDING / APPROVED / IN_USE */
    private String status;
}
