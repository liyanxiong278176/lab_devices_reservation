package com.lab.reservation.service;

import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.dashboard.DashboardMeVO;
import com.lab.reservation.vo.dashboard.DashboardOverviewVO;
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

    /**
     * 富指标聚合（管理员视角）。所有指标按角色范围过滤：
     * SYS_ADMIN 全量；LAB_ADMIN 仅自辖 lab 下设备。利用率/热力图走 Redis 缓存。
     *
     * @param groupBy 利用率分组维度：device（默认）/ category
     * @param days    利用率统计窗口天数（默认 30）
     */
    DashboardOverviewVO overview(SecurityUserDetails ud, String groupBy, int days);

    /**
     * 个人仪表盘（学生视角）：我的预约分布 / 趋势 / 常用品类 / 未读通知 / 我的报修。
     */
    DashboardMeVO me(SecurityUserDetails ud);
}
