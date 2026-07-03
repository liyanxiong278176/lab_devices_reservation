package com.lab.reservation.vo.dashboard;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

/**
 * 仪表盘个人视角（学生）。
 *
 * <p>面向 STUDENT，展示与「我」相关的统计：
 * <ul>
 *   <li>myReservationsByStatus：我的预约各状态数。</li>
 *   <li>myTrend30d：我近 30 天每日活跃预约数。</li>
 *   <li>myCategoryDist：我常用品类分布（按预约涉及的设备类目）。</li>
 *   <li>unreadCount：未读通知数。</li>
 *   <li>myRepairCount：我提交的报修单数。</li>
 * </ul>
 */
@Data
public class DashboardMeVO {

    /** 我的预约状态分布：PENDING / APPROVED / ... → count */
    private Map<String, Long> myReservationsByStatus;
    /** 我近 30 天每日活跃预约数 */
    private List<ReservationTrendItemVO> myTrend30d;
    /** 我常用品类 */
    private List<MyCategoryItem> myCategoryDist;
    /** 未读通知数 */
    private long unreadCount;
    /** 我提交的报修单数 */
    private long myRepairCount;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class MyCategoryItem {
        private Long categoryId;
        private String categoryName;
        private long count;
    }
}
