package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DashboardService;
import com.lab.reservation.vo.dashboard.DashboardSummaryVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 仪表盘接口（§8.8）。仅 LAB_ADMIN / SYS_ADMIN 可调。
 *
 * 当前仅返数字汇总；ECharts 可视化留待阶段3。
 */
@Tag(name = "仪表盘")
@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
@PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")
public class DashboardController {

    private final DashboardService dashboardService;

    @Operation(summary = "数字汇总：设备状态/今日预约/待审批/近7天趋势")
    @GetMapping("/summary")
    public Result<DashboardSummaryVO> summary(@AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(dashboardService.summary(ud));
    }
}
