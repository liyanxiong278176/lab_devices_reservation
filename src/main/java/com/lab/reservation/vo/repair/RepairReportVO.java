package com.lab.reservation.vo.repair;

import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 报修返回视图。规格 §8.9。
 */
@Data
public class RepairReportVO {
    private Long id;
    private Long deviceId;
    private String deviceName;
    private Long reporterId;
    private String reporterName;
    private String title;
    private String description;
    private List<String> imageUrls;
    private String status;
    private Long handlerId;
    private String resolutionNote;
    private LocalDateTime createdAt;
    private LocalDateTime resolvedAt;
}
