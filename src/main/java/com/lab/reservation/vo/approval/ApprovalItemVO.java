package com.lab.reservation.vo.approval;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 待审批列表项视图。
 *
 * 在 reservation 基础字段之外附带 deviceName / userName / realName，
 * 便于前端直接展示「谁 / 用哪个设备 / 何时 / 用途」，无需二次回填。
 */
@Data
public class ApprovalItemVO {
    private Long id;
    private Long userId;
    private String username;
    private String realName;
    private Long deviceId;
    private String deviceName;
    private String purpose;
    private LocalDateTime startTime;
    private LocalDateTime endTime;
    private Integer slotCount;
    /** PENDING（列表来源即待审批） */
    private String status;
    private LocalDateTime createdAt;
}
