package com.lab.reservation.dto.approval;

import jakarta.validation.constraints.NotEmpty;
import lombok.Data;

import java.util.List;

/**
 * 批量通过预约参数。
 *
 * 一次性通过多条待审批预约；任一非 PENDING 抛错回滚整体（{@code @Transactional}）。
 */
@Data
public class BatchApproveDTO {

    @NotEmpty(message = "预约 id 列表不能为空")
    private List<Long> ids;
}
