package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.time.LocalDateTime;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("reservation")
public class Reservation extends BaseEntity {
    private Long userId;
    private Long deviceId;
    private String purpose;
    private LocalDateTime startTime;
    private LocalDateTime endTime;
    private Integer slotCount;
    private String status;
    private String cancelReason;
    private Long approverId;
    private LocalDateTime approvedAt;
    private String rejectReason;
    private LocalDateTime checkInAt;
    private LocalDateTime checkOutAt;
}
