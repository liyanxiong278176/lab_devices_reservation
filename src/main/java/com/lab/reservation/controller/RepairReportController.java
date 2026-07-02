package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.aspect.Log;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.repair.RepairCreateDTO;
import com.lab.reservation.dto.repair.RepairHandleDTO;
import com.lab.reservation.entity.enums.RepairStatus;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RepairReportService;
import com.lab.reservation.vo.repair.RepairReportVO;
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
 * 报修接口（§8.9）。
 *
 * 用户：创建报修 / 查看自己的报修。
 * 管理员（repair:handle）：列表（按自辖 lab 范围过滤）/ take / resolve / reject。
 */
@Tag(name = "报修")
@RestController
@RequestMapping("/repair-reports")
@RequiredArgsConstructor
public class RepairReportController {

    private final RepairReportService repairReportService;

    @Operation(summary = "提交报修（用户，设备状态不变）")
    @PostMapping
    @Log("提交报修")
    public Result<Long> create(@Valid @RequestBody RepairCreateDTO dto,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(repairReportService.create(dto, ud.getUserId()));
    }

    @Operation(summary = "我的报修（按创建时间倒序分页）")
    @GetMapping("/mine")
    public Result<IPage<RepairReportVO>> mine(@RequestParam(defaultValue = "1") int page,
                                              @RequestParam(defaultValue = "10") int size,
                                              @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(repairReportService.mine(ud.getUserId(), page, size));
    }

    @Operation(summary = "报修列表（管理员，按 status 过滤 + 自辖 lab 范围）")
    @GetMapping
    @PreAuthorize("hasAuthority('repair:handle')")
    public Result<IPage<RepairReportVO>> list(@RequestParam(required = false) RepairStatus status,
                                              @RequestParam(defaultValue = "1") int page,
                                              @RequestParam(defaultValue = "10") int size,
                                              @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(repairReportService.list(status, page, size, ud));
    }

    @Operation(summary = "受理报修（PENDING → PROCESSING，设备置 MAINTENANCE）")
    @PostMapping("/{id}/take")
    @PreAuthorize("hasAuthority('repair:handle')")
    @Log("受理报修")
    public Result<Void> take(@PathVariable Long id,
                             @AuthenticationPrincipal SecurityUserDetails ud) {
        repairReportService.take(id, ud);
        return Result.ok();
    }

    @Operation(summary = "解决报修（PROCESSING → RESOLVED，设备置回 IDLE）")
    @PostMapping("/{id}/resolve")
    @PreAuthorize("hasAuthority('repair:handle')")
    @Log("解决报修")
    public Result<Void> resolve(@PathVariable Long id,
                                @Valid @RequestBody RepairHandleDTO dto,
                                @AuthenticationPrincipal SecurityUserDetails ud) {
        repairReportService.resolve(id, dto, ud);
        return Result.ok();
    }

    @Operation(summary = "驳回报修（PENDING → REJECTED，设备不变）")
    @PostMapping("/{id}/reject")
    @PreAuthorize("hasAuthority('repair:handle')")
    @Log("驳回报修")
    public Result<Void> reject(@PathVariable Long id,
                               @Valid @RequestBody RepairHandleDTO dto,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        repairReportService.reject(id, dto, ud);
        return Result.ok();
    }
}
