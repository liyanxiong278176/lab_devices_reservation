package com.lab.reservation.dto.reservation;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 预约创建参数。
 *
 * 起止时间须以 15 分钟为单位并对齐工作时段（08:00-22:00），
 * 校验在 {@link com.lab.reservation.service.SlotCalculatorService} 中完成。
 */
@Data
public class ReservationCreateDTO {

    @NotNull(message = "设备不能为空")
    private Long deviceId;

    @NotNull(message = "起始时间不能为空")
    private LocalDateTime startTime;

    @NotNull(message = "结束时间不能为空")
    private LocalDateTime endTime;

    @NotBlank(message = "用途不能为空")
    private String purpose;
}
