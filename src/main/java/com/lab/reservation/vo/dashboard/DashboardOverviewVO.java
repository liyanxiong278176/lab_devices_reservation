package com.lab.reservation.vo.dashboard;

import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.util.List;
import java.util.Map;

/**
 * 仪表盘富指标聚合（管理员视角）。
 *
 * <p>面向 LAB_ADMIN / SYS_ADMIN，所有指标按角色范围过滤：
 * <ul>
 *   <li>deviceStatus（饼图）：IDLE / IN_USE / MAINTENANCE 设备数。</li>
 *   <li>trend30d（折线）：近 30 天每日活跃预约数。</li>
 *   <li>utilization（柱状）：设备/类目利用率 = 占用 slot / 可用 slot。</li>
 *   <li>heatmap（热力图）：星期 × 小时段 的预约密度。</li>
 *   <li>categoryDist（饼/柱）：各类目设备数。</li>
 *   <li>repairStats（柱）：报修单各状态数。</li>
 *   <li>cards（数字卡片）：今日预约 / 待审批 / 近 7 天违规。</li>
 * </ul>
 */
@Data
public class DashboardOverviewVO {

    /** 设备状态分布：IDLE / IN_USE / MAINTENANCE → count */
    private Map<String, Long> deviceStatus;
    /** 近 30 天每日活跃预约数 */
    private List<ReservationTrendItemVO> trend30d;
    /** 设备/类目利用率 */
    private List<UtilizationItem> utilization;
    /** 星期 × 小时段预约密度（稀疏表示，缺失项视为 0） */
    private List<HeatmapCellVO> heatmap;
    /** 类目设备分布 */
    private List<CategoryDistItem> categoryDist;
    /** 报修状态分布：PENDING / PROCESSING / RESOLVED / REJECTED → count */
    private Map<String, Long> repairStats;
    /** 汇总数字卡片 */
    private Cards cards;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class UtilizationItem {
        /** 聚合键，如 "device:1" 或 "category:3" */
        private String key;
        /** 展示名（设备名 / 类目名） */
        private String label;
        private long occupiedSlots;
        private long availableSlots;
        /** 利用率 = occupied / available（available=0 时为 0） */
        private double utilizationRate;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CategoryDistItem {
        private Long categoryId;
        private String categoryName;
        private long deviceCount;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Cards {
        private long todayReservations;
        private long pendingApprovals;
        /** 近 7 天 VIOLATED + NO_SHOW 数 */
        private long weeklyViolations;
    }
}
