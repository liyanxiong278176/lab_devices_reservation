package com.lab.reservation.vo.dashboard;

import lombok.Data;

import java.util.List;

/**
 * 仪表盘数字汇总（§8.8）。
 *
 * 仅返回数字；ECharts 可视化留待阶段3。
 */
@Data
public class DashboardSummaryVO {
    /** 设备总数 */
    private long totalDevices;
    /** 空闲设备数 */
    private long idle;
    /** 使用中设备数 */
    private long inUse;
    /** 维护中设备数 */
    private long maintenance;
    /** 今日活跃预约数（PENDING / APPROVED / IN_USE，且 start_time 在今天） */
    private long todayReservations;
    /** 待审批预约数（按角色范围：SYS_ADMIN 全量，LAB_ADMIN 仅自辖 lab） */
    private long pendingApprovals;
    /** 近 7 天每天活跃预约数 */
    private List<ReservationTrendItemVO> weeklyReservationTrend;
}
