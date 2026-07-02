package com.lab.reservation.dto.repair;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.List;

/**
 * 报修创建参数（用户提交）。规格 §8.9。
 */
@Data
public class RepairCreateDTO {

    @NotNull(message = "设备不能为空")
    private Long deviceId;

    @NotBlank(message = "标题不能为空")
    private String title;

    private String description;

    /** 图片地址列表（可空）。 */
    private List<String> imageUrls;
}
