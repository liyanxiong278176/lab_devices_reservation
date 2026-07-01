package com.lab.reservation.dto.device;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 设备多条件检索参数。
 */
@Data
public class DeviceQueryDTO {
    private Long categoryId;
    private Long labId;
    /** IDLE / IN_USE / MAINTENANCE */
    private String status;
    /** 名称模糊匹配 */
    private String keyword;
    /** 0 / 1 */
    private Integer needApproval;
    private BigDecimal minPrice;
    private BigDecimal maxPrice;
    /** 默认 1 */
    private Long page = 1L;
    /** 默认 10 */
    private Long size = 10L;
}
