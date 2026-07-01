package com.lab.reservation.dto.device;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 设备创建/更新参数。
 */
@Data
public class DeviceSaveDTO {
    @NotBlank(message = "设备名称不能为空")
    private String name;
    @NotNull(message = "所属分类不能为空")
    private Long categoryId;
    @NotNull(message = "所属实验室不能为空")
    private Long labId;
    private String brand;
    private String model;
    private String specs;
    private String imageUrl;
    /** 0 不需要审批 / 1 需要 */
    private Integer needApproval = 0;
    private BigDecimal maxReservationHours;
    private BigDecimal pricePerHour;
    private List<String> tags;
    private String description;
}
