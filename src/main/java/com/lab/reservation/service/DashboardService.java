package com.lab.reservation.service;

import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.dashboard.DashboardSummaryVO;

/**
 * 仪表盘统计服务（§8.8）。
 */
public interface DashboardService {

    /**
     * 获取仪表盘数字汇总。
     * pendingApprovals / todayReservations 按角色范围统计：
     * SYS_ADMIN 全量，LAB_ADMIN 仅自辖 lab。
     */
    DashboardSummaryVO summary(SecurityUserDetails ud);
}
