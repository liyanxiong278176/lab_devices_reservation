package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.DeviceStatus;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DashboardService;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.vo.dashboard.DashboardSummaryVO;
import com.lab.reservation.vo.dashboard.ReservationTrendItemVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 仪表盘统计实现。
 *
 * <p>统计项（§8.8）：
 * <ul>
 *   <li>设备状态分布：IDLE / IN_USE / MAINTENANCE，内存分组（设备量小）。</li>
 *   <li>todayReservations：今日开始且活跃（PENDING / APPROVED / IN_USE）。</li>
 *   <li>pendingApprovals：PENDING 数，按角色范围过滤。
 *       SYS_ADMIN 全量；LAB_ADMIN 仅统计自辖 lab 下设备（复用 LabScopeHelper）。</li>
 *   <li>weeklyReservationTrend：近 7 天每天活跃预约数，GROUP BY 聚合 + Java 侧补全 7 天为 0。</li>
 * </ul>
 */
@Service
@RequiredArgsConstructor
public class DashboardServiceImpl implements DashboardService {

    private final DeviceMapper deviceMapper;
    private final ReservationMapper reservationMapper;
    private final LabScopeHelper labScopeHelper;

    @Override
    public DashboardSummaryVO summary(SecurityUserDetails ud) {
        DashboardSummaryVO vo = new DashboardSummaryVO();

        // ============ 设备状态分布 ============
        List<Device> devices = deviceMapper.selectList(null);
        Map<String, Long> statusCount = devices.stream()
                .filter(d -> d.getStatus() != null)
                .collect(Collectors.groupingBy(Device::getStatus, Collectors.counting()));
        vo.setTotalDevices(devices.size());
        vo.setIdle(statusCount.getOrDefault(DeviceStatus.IDLE.name(), 0L));
        vo.setInUse(statusCount.getOrDefault(DeviceStatus.IN_USE.name(), 0L));
        vo.setMaintenance(statusCount.getOrDefault(DeviceStatus.MAINTENANCE.name(), 0L));

        // ============ 今日活跃预约 ============
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime tomorrowStart = todayStart.plusDays(1);
        long todayReservations = countActiveReservations(todayStart, tomorrowStart, null);
        vo.setTodayReservations(todayReservations);

        // ============ 待审批（按角色范围） ============
        vo.setPendingApprovals(countPendingApprovals(ud));

        // ============ 近 7 天趋势 ============
        vo.setWeeklyReservationTrend(buildWeeklyTrend());

        return vo;
    }

    /**
     * 统计指定日期区间内、指定设备范围内的活跃预约数。
     *
     * @param from         起始（含）
     * @param to           结束（不含）
     * @param scopedDeviceIds 设备范围；null 表示不限（SYS_ADMIN / 全量设备统计）
     */
    private long countActiveReservations(LocalDateTime from, LocalDateTime to, Set<Long> scopedDeviceIds) {
        LambdaQueryWrapper<Reservation> qw = new LambdaQueryWrapper<Reservation>()
                .ge(Reservation::getStartTime, from)
                .lt(Reservation::getStartTime, to)
                .in(Reservation::getStatus,
                        ReservationStatus.PENDING.name(),
                        ReservationStatus.APPROVED.name(),
                        ReservationStatus.IN_USE.name());
        if (scopedDeviceIds != null) {
            if (scopedDeviceIds.isEmpty()) {
                return 0L;
            }
            qw.in(Reservation::getDeviceId, scopedDeviceIds);
        }
        return reservationMapper.selectCount(qw);
    }

    /**
     * 待审批数：SYS_ADMIN 全量 PENDING；LAB_ADMIN 仅自辖 lab 下设备的 PENDING。
     */
    private long countPendingApprovals(SecurityUserDetails ud) {
        List<Long> labIds = labScopeHelper.managedLabIds(ud);

        // LAB_ADMIN 未辖任何 lab → 0
        if (labIds != null && labIds.isEmpty()) {
            return 0L;
        }

        Set<Long> scopedDeviceIds = null;
        if (labIds != null) {
            List<Device> devices = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                    .in(Device::getLabId, labIds));
            scopedDeviceIds = devices.stream().map(Device::getId).collect(Collectors.toSet());
            // 自辖 lab 下无任何设备 → 0
            if (scopedDeviceIds.isEmpty()) {
                return 0L;
            }
        }

        LambdaQueryWrapper<Reservation> qw = new LambdaQueryWrapper<Reservation>()
                .eq(Reservation::getStatus, ReservationStatus.PENDING.name());
        if (scopedDeviceIds != null) {
            qw.in(Reservation::getDeviceId, scopedDeviceIds);
        }
        return reservationMapper.selectCount(qw);
    }

    /**
     * 近 7 天趋势：聚合查询 + Java 侧补全缺失日期为 0。
     * 范围：[今天-6天 00:00, 今天+1天 00:00)，共 7 天。
     */
    private List<ReservationTrendItemVO> buildWeeklyTrend() {
        LocalDate today = LocalDate.now();
        LocalDateTime from = LocalDateTime.of(today.minusDays(6), LocalTime.MIN);

        List<ReservationTrendItemVO> rows = reservationMapper.selectDailyActiveTrend(from);
        Map<LocalDate, Long> map = new HashMap<>();
        if (rows != null) {
            for (ReservationTrendItemVO r : rows) {
                if (r.getDate() != null) {
                    map.put(r.getDate(), r.getCount());
                }
            }
        }

        List<ReservationTrendItemVO> result = new ArrayList<>(7);
        for (int i = 6; i >= 0; i--) {
            LocalDate d = today.minusDays(i);
            result.add(new ReservationTrendItemVO(d, map.getOrDefault(d, 0L)));
        }
        return result;
    }
}
