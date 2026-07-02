package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.aspect.Log;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.approval.BatchApproveDTO;
import com.lab.reservation.dto.approval.RejectDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ApprovalService;
import com.lab.reservation.vo.approval.ApprovalItemVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 审批接口（§8.6）。全部需要 device:approve 权限（LAB_ADMIN / SYS_ADMIN）。
 *
 * LAB_ADMIN 仅见/操作自辖 lab 下设备的预约；SYS_ADMIN 全量。范围隔离在 service 层
 * 经 {@link com.lab.reservation.service.LabScopeHelper} 完成。
 */
@Tag(name = "审批")
@RestController
@RequestMapping("/approvals")
@RequiredArgsConstructor
@PreAuthorize("hasAuthority('device:approve')")
public class ApprovalController {

    private final ApprovalService approvalService;

    @Operation(summary = "待审批列表（按自辖 lab 范围过滤）")
    @GetMapping("/pending")
    public Result<IPage<ApprovalItemVO>> pending(@RequestParam(defaultValue = "1") int page,
                                                 @RequestParam(defaultValue = "10") int size,
                                                 @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(approvalService.pendingList(page, size, ud));
    }

    @Operation(summary = "通过预约（PENDING → APPROVED，保留槽）")
    @PostMapping("/{id}/approve")
    @Log("审批通过")
    public Result<Void> approve(@PathVariable Long id,
                                @AuthenticationPrincipal SecurityUserDetails ud) {
        approvalService.approve(id, ud);
        return Result.ok();
    }

    @Operation(summary = "拒绝预约（PENDING → REJECTED，释放槽）")
    @PostMapping("/{id}/reject")
    @Log("审批拒绝")
    public Result<Void> reject(@PathVariable Long id,
                               @Valid @RequestBody RejectDTO dto,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        approvalService.reject(id, dto.getReason(), ud);
        return Result.ok();
    }

    @Operation(summary = "批量通过（任一非 PENDING 回滚整体）")
    @PostMapping("/batch-approve")
    @Log("批量审批通过")
    public Result<Void> batchApprove(@Valid @RequestBody BatchApproveDTO dto,
                                     @AuthenticationPrincipal SecurityUserDetails ud) {
        approvalService.batchApprove(dto.getIds(), ud);
        return Result.ok();
    }
}
