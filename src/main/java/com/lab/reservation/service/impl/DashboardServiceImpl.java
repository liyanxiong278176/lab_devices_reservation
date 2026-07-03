package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.DeviceCategory;
import com.lab.reservation.entity.Notification;
import com.lab.reservation.entity.RepairReport;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.DeviceStatus;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.DeviceCategoryMapper;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.NotificationMapper;
import com.lab.reservation.mapper.RepairReportMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DashboardService;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.vo.dashboard.DashboardMeVO;
import com.lab.reservation.vo.dashboard.DashboardOverviewVO;
import com.lab.reservation.vo.dashboard.DashboardSummaryVO;
import com.lab.reservation.vo.dashboard.HeatmapCellVO;
import com.lab.reservation.vo.dashboard.OccupiedSlotCountVO;
import com.lab.reservation.vo.dashboard.ReservationTrendItemVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 仪表盘统计实现。
 *
 * <p>三类接口：
 * <ul>
 *   <li>{@link #summary} —— 原数字汇总（保留向后兼容）。</li>
 *   <li>{@link #overview} —— 富指标聚合（LAB_ADMIN / SYS_ADMIN），利用率/热力图走 Redis 缓存。</li>
 *   <li>{@link #me} —— 个人仪表盘（STUDENT / 任意已登录用户）。</li>
 * </ul>
 *
 * <p>角色范围（复用 {@link LabScopeHelper}）：
 * <ul>
 *   <li>SYS_ADMIN（managedLabIds == null）—— 全量，设备过滤传 null。</li>
 *   <li>LAB_ADMIN（managedLabIds 非空）—— 仅自辖 lab 下设备；空列表则所有指标为空/0。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DashboardServiceImpl implements DashboardService {

    private final DeviceMapper deviceMapper;
    private final ReservationMapper reservationMapper;
    private final ReservationItemMapper reservationItemMapper;
    private final RepairReportMapper repairReportMapper;
    private final DeviceCategoryMapper deviceCategoryMapper;
    private final NotificationMapper notificationMapper;
    private final LabScopeHelper labScopeHelper;
    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;

    @Value("${lab.slot.minutes:15}")
    private int slotMinutes;
    @Value("${lab.slot.work-start:08:00}")
    private LocalTime workStart;
    @Value("${lab.slot.work-end:22:00}")
    private LocalTime workEnd;
    @Value("${lab.dashboard.cache-ttl-minutes:5}")
    private int cacheTtlMinutes;

    // ============================ summary（保留） ============================

    @Override
    public DashboardSummaryVO summary(SecurityUserDetails ud) {
        DashboardSummaryVO vo = new DashboardSummaryVO();

        List<Device> devices = deviceMapper.selectList(null);
        Map<String, Long> statusCount = devices.stream()
                .filter(d -> d.getStatus() != null)
                .collect(Collectors.groupingBy(Device::getStatus, Collectors.counting()));
        vo.setTotalDevices(devices.size());
        vo.setIdle(statusCount.getOrDefault(DeviceStatus.IDLE.name(), 0L));
        vo.setInUse(statusCount.getOrDefault(DeviceStatus.IN_USE.name(), 0L));
        vo.setMaintenance(statusCount.getOrDefault(DeviceStatus.MAINTENANCE.name(), 0L));

        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime tomorrowStart = todayStart.plusDays(1);
        long todayReservations = countActiveReservations(todayStart, tomorrowStart, null);
        vo.setTodayReservations(todayReservations);

        vo.setPendingApprovals(countPendingApprovals(ud));

        vo.setWeeklyReservationTrend(buildWeeklyTrend());

        return vo;
    }

    // ============================ overview（富指标） ============================

    @Override
    public DashboardOverviewVO overview(SecurityUserDetails ud, String groupBy, int days) {
        DashboardOverviewVO vo = new DashboardOverviewVO();

        // ---- 角色范围解析（只查一次） ----
        List<Long> labIds = labScopeHelper.managedLabIds(ud);
        boolean isSysAdmin = (labIds == null);
        String role = isSysAdmin ? "sys" : "lab";

        List<Device> devices;
        // null = 不加设备过滤（SYS_ADMIN 全量）；非空列表 = LAB_ADMIN 自辖设备；空列表 = LAB_ADMIN 无设备
        List<Long> deviceIdsForQuery;
        if (isSysAdmin) {
            devices = deviceMapper.selectList(null);
            deviceIdsForQuery = null;
        } else if (labIds.isEmpty()) {
            devices = Collections.emptyList();
            deviceIdsForQuery = Collections.emptyList();
        } else {
            devices = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                    .in(Device::getLabId, labIds));
            deviceIdsForQuery = devices.stream().map(Device::getId).collect(Collectors.toList());
        }

        // 类目名缓存（categoryDist + utilization 都会用到）
        Map<Long, String> categoryNames = loadCategoryNames(devices);

        // ---- 轻指标（每次实时计算） ----
        vo.setDeviceStatus(deviceStatusDist(devices));
        vo.setTrend30d(buildTrend30d(deviceIdsForQuery));
        vo.setCategoryDist(categoryDist(devices, categoryNames));
        vo.setRepairStats(repairStats(deviceIdsForQuery));
        vo.setCards(buildCards(ud, deviceIdsForQuery));

        // ---- 重指标（Redis 缓存） ----
        vo.setUtilization(computeUtilizationCached(role, ud.getUserId(), devices,
                deviceIdsForQuery, groupBy, days, categoryNames));
        vo.setHeatmap(computeHeatmapCached(role, ud.getUserId(), deviceIdsForQuery));

        return vo;
    }

    // ============================ me（个人） ============================

    @Override
    public DashboardMeVO me(SecurityUserDetails ud) {
        DashboardMeVO vo = new DashboardMeVO();
        Long userId = ud.getUserId();

        // 我的预约各状态数
        List<Reservation> myReservations = reservationMapper.selectList(
                new LambdaQueryWrapper<Reservation>().eq(Reservation::getUserId, userId));
        vo.setMyReservationsByStatus(myReservations.stream()
                .filter(r -> r.getStatus() != null)
                .collect(Collectors.groupingBy(Reservation::getStatus, Collectors.counting())));

        // 近 30 天趋势
        vo.setMyTrend30d(buildMyTrend30d(userId));

        // 常用品类
        vo.setMyCategoryDist(buildMyCategoryDist(myReservations));

        // 未读通知
        vo.setUnreadCount(notificationMapper.selectCount(
                new LambdaQueryWrapper<Notification>()
                        .eq(Notification::getUserId, userId)
                        .eq(Notification::getIsRead, 0)));

        // 我的报修
        vo.setMyRepairCount(repairReportMapper.selectCount(
                new LambdaQueryWrapper<RepairReport>()
                        .eq(RepairReport::getReporterId, userId)));

        return vo;
    }

    // ============================ overview 组件 ============================

    private Map<String, Long> deviceStatusDist(List<Device> devices) {
        return devices.stream()
                .filter(d -> d.getStatus() != null)
                .collect(Collectors.groupingBy(Device::getStatus, Collectors.counting()));
    }

    private List<ReservationTrendItemVO> buildTrend30d(List<Long> deviceIdsForQuery) {
        LocalDate today = LocalDate.now();
        LocalDateTime from = LocalDateTime.of(today.minusDays(29), LocalTime.MIN);
        Map<LocalDate, Long> map = new HashMap<>();
        // 仅在有范围数据时查询（非空列表 = LAB_ADMIN 无设备 → 跳过，返回全 0）
        if (deviceIdsForQuery == null || !deviceIdsForQuery.isEmpty()) {
            List<ReservationTrendItemVO> rows =
                    reservationMapper.selectDailyActiveTrendScoped(from, deviceIdsForQuery);
            if (rows != null) {
                for (ReservationTrendItemVO r : rows) {
                    if (r.getDate() != null) {
                        map.put(r.getDate(), r.getCount());
                    }
                }
            }
        }
        List<ReservationTrendItemVO> result = new ArrayList<>(30);
        for (int i = 29; i >= 0; i--) {
            LocalDate d = today.minusDays(i);
            result.add(new ReservationTrendItemVO(d, map.getOrDefault(d, 0L)));
        }
        return result;
    }

    private List<DashboardOverviewVO.CategoryDistItem> categoryDist(List<Device> devices,
                                                                     Map<Long, String> categoryNames) {
        Map<Long, Long> counts = devices.stream()
                .filter(d -> d.getCategoryId() != null)
                .collect(Collectors.groupingBy(Device::getCategoryId, Collectors.counting()));
        return counts.entrySet().stream()
                .map(e -> new DashboardOverviewVO.CategoryDistItem(
                        e.getKey(), categoryNames.getOrDefault(e.getKey(), "未分类"), e.getValue()))
                .collect(Collectors.toList());
    }

    private Map<String, Long> repairStats(List<Long> deviceIdsForQuery) {
        if (deviceIdsForQuery != null && deviceIdsForQuery.isEmpty()) {
            return Collections.emptyMap();
        }
        LambdaQueryWrapper<RepairReport> qw = new LambdaQueryWrapper<>();
        if (deviceIdsForQuery != null) {
            qw.in(RepairReport::getDeviceId, deviceIdsForQuery);
        }
        List<RepairReport> reports = repairReportMapper.selectList(qw);
        return reports.stream()
                .filter(r -> r.getStatus() != null)
                .collect(Collectors.groupingBy(RepairReport::getStatus, Collectors.counting()));
    }

    private DashboardOverviewVO.Cards buildCards(SecurityUserDetails ud, List<Long> deviceIdsForQuery) {
        DashboardOverviewVO.Cards c = new DashboardOverviewVO.Cards();
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime tomorrowStart = todayStart.plusDays(1);
        Set<Long> scopedSet = deviceIdsForQuery == null ? null : new HashSet<>(deviceIdsForQuery);
        c.setTodayReservations(countActiveReservations(todayStart, tomorrowStart, scopedSet));
        c.setPendingApprovals(countPendingApprovals(ud));
        c.setWeeklyViolations(countWeeklyViolations(deviceIdsForQuery));
        return c;
    }

    private long countWeeklyViolations(List<Long> deviceIdsForQuery) {
        if (deviceIdsForQuery != null && deviceIdsForQuery.isEmpty()) {
            return 0L;
        }
        LocalDateTime weekAgo = LocalDateTime.of(LocalDate.now().minusDays(6), LocalTime.MIN);
        LambdaQueryWrapper<Reservation> qw = new LambdaQueryWrapper<Reservation>()
                .ge(Reservation::getStartTime, weekAgo)
                .in(Reservation::getStatus,
                        ReservationStatus.VIOLATED.name(),
                        ReservationStatus.NO_SHOW.name());
        if (deviceIdsForQuery != null) {
            qw.in(Reservation::getDeviceId, deviceIdsForQuery);
        }
        return reservationMapper.selectCount(qw);
    }

    // ============================ 利用率（缓存） ============================

    private List<DashboardOverviewVO.UtilizationItem> computeUtilizationCached(
            String role, Long userId, List<Device> devices, List<Long> deviceIdsForQuery,
            String groupBy, int days, Map<Long, String> categoryNames) {
        String key = String.format("dash:util:%s:%s:%s:%d", role, userId, groupBy, days);
        List<DashboardOverviewVO.UtilizationItem> cached = readCache(key,
                new TypeReference<List<DashboardOverviewVO.UtilizationItem>>() {});
        if (cached != null) {
            return cached;
        }
        List<DashboardOverviewVO.UtilizationItem> result =
                computeUtilization(devices, deviceIdsForQuery, groupBy, days, categoryNames);
        writeCache(key, result);
        return result;
    }

    private List<DashboardOverviewVO.UtilizationItem> computeUtilization(
            List<Device> devices, List<Long> deviceIdsForQuery, String groupBy, int days,
            Map<Long, String> categoryNames) {
        if (devices.isEmpty() || (deviceIdsForQuery != null && deviceIdsForQuery.isEmpty())) {
            return Collections.emptyList();
        }
        LocalDate to = LocalDate.now();
        LocalDate from = to.minusDays(Math.max(1, days) - 1L);
        List<OccupiedSlotCountVO> rows =
                reservationItemMapper.selectOccupiedSlotCounts(deviceIdsForQuery, from, to);
        Map<Long, Long> occupied = rows == null ? Collections.emptyMap()
                : rows.stream().collect(Collectors.toMap(
                        OccupiedSlotCountVO::getDeviceId, OccupiedSlotCountVO::getOccupied, Long::sum));
        long availablePerDevice = (long) slotsPerDay() * days;

        if ("category".equalsIgnoreCase(groupBy)) {
            // 按类目聚合：累加类目下各设备的 occupied / available
            Map<Long, long[]> agg = new HashMap<>(); // categoryId -> [occupied, available]
            for (Device d : devices) {
                if (d.getCategoryId() == null) {
                    continue;
                }
                long occ = occupied.getOrDefault(d.getId(), 0L);
                long[] a = agg.computeIfAbsent(d.getCategoryId(), k -> new long[2]);
                a[0] += occ;
                a[1] += availablePerDevice;
            }
            return agg.entrySet().stream()
                    .map(e -> new DashboardOverviewVO.UtilizationItem(
                            "category:" + e.getKey(),
                            categoryNames.getOrDefault(e.getKey(), "未分类"),
                            e.getValue()[0], e.getValue()[1],
                            rate(e.getValue()[0], e.getValue()[1])))
                    .collect(Collectors.toList());
        }
        // 默认按设备
        return devices.stream().map(d -> {
            long occ = occupied.getOrDefault(d.getId(), 0L);
            return new DashboardOverviewVO.UtilizationItem(
                    "device:" + d.getId(), d.getName(),
                    occ, availablePerDevice, rate(occ, availablePerDevice));
        }).collect(Collectors.toList());
    }

    private static double rate(long occupied, long available) {
        return available == 0 ? 0.0 : (double) occupied / available;
    }

    // ============================ 热力图（缓存） ============================

    private List<HeatmapCellVO> computeHeatmapCached(String role, Long userId, List<Long> deviceIdsForQuery) {
        String key = String.format("dash:heat:%s:%s", role, userId);
        List<HeatmapCellVO> cached = readCache(key, new TypeReference<List<HeatmapCellVO>>() {});
        if (cached != null) {
            return cached;
        }
        List<HeatmapCellVO> result = computeHeatmap(deviceIdsForQuery);
        writeCache(key, result);
        return result;
    }

    private List<HeatmapCellVO> computeHeatmap(List<Long> deviceIdsForQuery) {
        if (deviceIdsForQuery != null && deviceIdsForQuery.isEmpty()) {
            return Collections.emptyList();
        }
        LocalDate to = LocalDate.now();
        LocalDate from = to.minusDays(29);
        List<HeatmapCellVO> rows = reservationItemMapper.selectHeatmap(
                deviceIdsForQuery, from, to, slotsPerHour());
        return rows == null ? Collections.emptyList() : rows;
    }

    // ============================ me 组件 ============================

    private List<ReservationTrendItemVO> buildMyTrend30d(Long userId) {
        LocalDate today = LocalDate.now();
        LocalDateTime from = LocalDateTime.of(today.minusDays(29), LocalTime.MIN);
        List<Reservation> rows = reservationMapper.selectList(
                new LambdaQueryWrapper<Reservation>()
                        .eq(Reservation::getUserId, userId)
                        .ge(Reservation::getStartTime, from)
                        .in(Reservation::getStatus,
                                ReservationStatus.PENDING.name(),
                                ReservationStatus.APPROVED.name(),
                                ReservationStatus.IN_USE.name()));
        Map<LocalDate, Long> map = rows.stream()
                .filter(r -> r.getStartTime() != null)
                .collect(Collectors.groupingBy(r -> r.getStartTime().toLocalDate(), Collectors.counting()));
        List<ReservationTrendItemVO> result = new ArrayList<>(30);
        for (int i = 29; i >= 0; i--) {
            LocalDate d = today.minusDays(i);
            result.add(new ReservationTrendItemVO(d, map.getOrDefault(d, 0L)));
        }
        return result;
    }

    private List<DashboardMeVO.MyCategoryItem> buildMyCategoryDist(List<Reservation> myReservations) {
        Set<Long> deviceIds = myReservations.stream()
                .map(Reservation::getDeviceId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        if (deviceIds.isEmpty()) {
            return Collections.emptyList();
        }
        List<Device> devices = deviceMapper.selectList(
                new LambdaQueryWrapper<Device>().in(Device::getId, deviceIds));
        Map<Long, Long> catCounts = devices.stream()
                .filter(d -> d.getCategoryId() != null)
                .collect(Collectors.groupingBy(Device::getCategoryId, Collectors.counting()));
        Map<Long, String> catNames = loadCategoryNamesByIds(catCounts.keySet());
        return catCounts.entrySet().stream()
                .map(e -> new DashboardMeVO.MyCategoryItem(
                        e.getKey(), catNames.getOrDefault(e.getKey(), "未分类"), e.getValue()))
                .collect(Collectors.toList());
    }

    // ============================ 工具 ============================

    private Map<Long, String> loadCategoryNames(List<Device> devices) {
        Set<Long> catIds = devices.stream()
                .map(Device::getCategoryId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        return loadCategoryNamesByIds(catIds);
    }

    private Map<Long, String> loadCategoryNamesByIds(Set<Long> categoryIds) {
        if (categoryIds.isEmpty()) {
            return Collections.emptyMap();
        }
        List<DeviceCategory> cats = deviceCategoryMapper.selectList(
                new LambdaQueryWrapper<DeviceCategory>().in(DeviceCategory::getId, categoryIds));
        return cats.stream().collect(Collectors.toMap(DeviceCategory::getId,
                c -> c.getName() == null ? "未分类" : c.getName(), (a, b) -> a));
    }

    private int slotsPerDay() {
        return (int) Duration.between(workStart, workEnd).toMinutes() / slotMinutes;
    }

    private int slotsPerHour() {
        return 60 / slotMinutes;
    }

    /** 读缓存，命中返回反序列化值；miss/异常返回 null。 */
    private <T> T readCache(String key, TypeReference<T> typeRef) {
        try {
            String json = stringRedisTemplate.opsForValue().get(key);
            if (json != null) {
                return objectMapper.readValue(json, typeRef);
            }
        } catch (Exception e) {
            log.warn("dashboard cache read fail key={}, err={}", key, e.getMessage());
        }
        return null;
    }

    /** 写缓存，异常忽略（不影响主流程）。 */
    private void writeCache(String key, Object data) {
        try {
            String json = objectMapper.writeValueAsString(data);
            stringRedisTemplate.opsForValue().set(key, json,
                    (long) cacheTtlMinutes * 60, TimeUnit.SECONDS);
        } catch (Exception e) {
            log.warn("dashboard cache write fail key={}, err={}", key, e.getMessage());
        }
    }

    // ============================ summary 复用（私有） ============================

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

    private long countPendingApprovals(SecurityUserDetails ud) {
        List<Long> labIds = labScopeHelper.managedLabIds(ud);
        if (labIds != null && labIds.isEmpty()) {
            return 0L;
        }
        Set<Long> scopedDeviceIds = null;
        if (labIds != null) {
            List<Device> devices = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                    .in(Device::getLabId, labIds));
            scopedDeviceIds = devices.stream().map(Device::getId).collect(Collectors.toSet());
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
