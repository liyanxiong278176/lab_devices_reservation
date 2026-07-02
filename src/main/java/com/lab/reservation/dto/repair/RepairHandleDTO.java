package com.lab.reservation.dto.repair;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 报修处理参数：resolve 的处理说明 / reject 的驳回理由，统一用 resolutionNote 承载。规格 §8.9。
 */
@Data
public class RepairHandleDTO {

    @NotBlank(message = "处理说明不能为空")
    private String resolutionNote;
}
