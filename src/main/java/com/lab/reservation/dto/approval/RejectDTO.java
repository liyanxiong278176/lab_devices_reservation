package com.lab.reservation.dto.approval;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 拒绝预约参数。
 *
 * status = REJECTED 时须记录拒绝理由（{@code reject_reason}），便于用户复盘。
 */
@Data
public class RejectDTO {

    @NotBlank(message = "拒绝理由不能为空")
    private String reason;
}
