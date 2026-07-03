package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DashboardService;
import com.lab.reservation.vo.dashboard.DashboardMeVO;
import com.lab.reservation.vo.dashboard.DashboardOverviewVO;
import com.lab.reservation.vo.dashboard.DashboardSummaryVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 仪表盘接口（§8.8）。
 *
 * <ul>
 *   <li>GET /dashboard/summary —— 原数字汇总（LAB_ADMIN / SYS_ADMIN）。</li>
 *   <li>GET /dashboard/overview —— 富指标聚合（LAB_ADMIN / SYS_ADMIN），含利用率/热力图等。</li>
 *   <li>GET /dashboard/me —— 个人仪表盘（任意已登录用户）。</li>
 * </ul>
 */
@Tag(name = "仪表盘")
@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final DashboardService dashboardService;

    @Operation(summary = "数字汇总：设备状态/今日预约/待审批/近7天趋势")
    @PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")
    @GetMapping("/summary")
    public Result<DashboardSummaryVO> summary(@AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(dashboardService.summary(ud));
    }

    @Operation(summary = "富指标聚合：利用率/热力图/类目/报修/趋势（角色范围过滤）")
    @PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")
    @GetMapping("/overview")
    public Result<DashboardOverviewVO> overview(@AuthenticationPrincipal SecurityUserDetails ud,
                                                @RequestParam(defaultValue = "device") String groupBy,
                                                @RequestParam(defaultValue = "30") int days) {
        return Result.ok(dashboardService.overview(ud, groupBy, days));
    }

    @Operation(summary = "个人仪表盘：我的预约/趋势/品类/未读/报修")
    @PreAuthorize("isAuthenticated()")
    @GetMapping("/me")
    public Result<DashboardMeVO> me(@AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(dashboardService.me(ud));
    }
}
