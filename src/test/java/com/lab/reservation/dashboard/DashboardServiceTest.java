package com.lab.reservation.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.DeviceCategory;
import com.lab.reservation.entity.Notification;
import com.lab.reservation.entity.RepairReport;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.DeviceStatus;
import com.lab.reservation.entity.enums.RepairStatus;
import com.lab.reservation.mapper.DeviceCategoryMapper;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.NotificationMapper;
import com.lab.reservation.mapper.RepairReportMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.service.impl.DashboardServiceImpl;
import com.lab.reservation.vo.dashboard.DashboardMeVO;
import com.lab.reservation.vo.dashboard.DashboardOverviewVO;
import com.lab.reservation.vo.dashboard.HeatmapCellVO;
import com.lab.reservation.vo.dashboard.OccupiedSlotCountVO;
import com.lab.reservation.vo.dashboard.ReservationTrendItemVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 仪表盘富指标聚合 TDD 测试（mock mapper + StringRedisTemplate，纯单测）。
 *
 * <p>核心断言：
 * <ul>
 *   <li>overview 组装全部 7 个 widget（deviceStatus/trend30d/utilization/heatmap/categoryDist/repairStats/cards）。</li>
 *   <li>LAB_ADMIN 范围：聚合查询传入自辖设备 id 列表。</li>
 *   <li>SYS_ADMIN 范围：聚合查询传 null（不加设备过滤）。</li>
 *   <li>Redis 缓存命中时跳过重算（重 mapper 不被二次调用）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class DashboardServiceTest {

    @Mock private DeviceMapper deviceMapper;
    @Mock private ReservationMapper reservationMapper;
    @Mock private ReservationItemMapper reservationItemMapper;
    @Mock private RepairReportMapper repairReportMapper;
    @Mock private DeviceCategoryMapper deviceCategoryMapper;
    @Mock private NotificationMapper notificationMapper;
    @Mock private LabScopeHelper labScopeHelper;
    @Mock private StringRedisTemplate stringRedisTemplate;
    @Mock private ValueOperations<String, String> valueOps;

    private DashboardServiceImpl service;

    private static final long SYS_UID = 1L;
    private static final long LAB_UID = 5L;
    private static final long LAB_ID = 10L;

    @BeforeEach
    void setUp() {
        service = new DashboardServiceImpl(
                deviceMapper, reservationMapper, reservationItemMapper,
                repairReportMapper, deviceCategoryMapper, notificationMapper,
                labScopeHelper, stringRedisTemplate, new ObjectMapper());
        ReflectionTestUtils.setField(service, "slotMinutes", 15);
        ReflectionTestUtils.setField(service, "workStart", LocalTime.of(8, 0));
        ReflectionTestUtils.setField(service, "workEnd", LocalTime.of(22, 0));
        ReflectionTestUtils.setField(service, "cacheTtlMinutes", 5);

        // 公共桩：Redis ops 返回 mock valueOps（默认 get=null=cache miss）；selectCount 默认 0
        lenient().when(stringRedisTemplate.opsForValue()).thenReturn(valueOps);
        lenient().when(valueOps.get(anyString())).thenReturn(null);
        lenient().when(reservationMapper.selectCount(any())).thenReturn(0L);
    }

    // ---------- 工具 ----------

    private SecurityUserDetails sysAdmin() {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(SYS_UID);
        when(labScopeHelper.managedLabIds(ud)).thenReturn(null);
        return ud;
    }

    private SecurityUserDetails labAdmin() {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(LAB_UID);
        when(labScopeHelper.managedLabIds(ud)).thenReturn(List.of(LAB_ID));
        return ud;
    }

    private Device device(long id, String name, long catId, String status) {
        Device d = new Device();
        d.setId(id);
        d.setName(name);
        d.setCategoryId(catId);
        d.setStatus(status);
        d.setLabId(LAB_ID);
        return d;
    }

    private DeviceCategory category(long id, String name) {
        DeviceCategory c = new DeviceCategory();
        c.setId(id);
        c.setName(name);
        return c;
    }

    // ---------- 测试 ----------

    @Test
    void overview_assembles_all_widgets() {
        SecurityUserDetails ud = sysAdmin();
        when(deviceMapper.selectList(any())).thenReturn(List.of(
                device(1L, "光谱仪", 100L, DeviceStatus.IDLE.name()),
                device(2L, "示波器", 200L, DeviceStatus.IN_USE.name())));
        when(deviceCategoryMapper.selectList(any())).thenReturn(List.of(
                category(100L, "光学"), category(200L, "电子")));
        when(reservationMapper.selectDailyActiveTrendScoped(any(), any()))
                .thenReturn(List.of(new ReservationTrendItemVO(LocalDate.now(), 3L)));
        when(reservationItemMapper.selectOccupiedSlotCounts(any(), any(), any()))
                .thenReturn(List.of(new OccupiedSlotCountVO(1L, 10L),
                        new OccupiedSlotCountVO(2L, 20L)));
        when(reservationItemMapper.selectHeatmap(any(), any(), any(), anyInt()))
                .thenReturn(List.of(new HeatmapCellVO(2, 9, 5L)));
        when(repairReportMapper.selectList(any())).thenReturn(List.of(
                repairReport(RepairStatus.PENDING)));
        when(reservationMapper.selectCount(any())).thenReturn(5L);

        DashboardOverviewVO vo = service.overview(ud, "device", 30);

        // deviceStatus
        assertNotNull(vo.getDeviceStatus());
        assertEquals(1L, vo.getDeviceStatus().get(DeviceStatus.IDLE.name()));
        assertEquals(1L, vo.getDeviceStatus().get(DeviceStatus.IN_USE.name()));

        // trend30d
        assertNotNull(vo.getTrend30d());
        assertEquals(30, vo.getTrend30d().size());
        assertEquals(3L, vo.getTrend30d().get(29).getCount());

        // utilization
        assertNotNull(vo.getUtilization());
        assertEquals(2, vo.getUtilization().size());
        // availableSlots = 56/day * 30 = 1680
        DashboardOverviewVO.UtilizationItem u0 = vo.getUtilization().get(0);
        assertEquals(10L, u0.getOccupiedSlots());
        assertEquals(1680L, u0.getAvailableSlots());

        // heatmap
        assertNotNull(vo.getHeatmap());
        assertFalse(vo.getHeatmap().isEmpty());
        assertEquals(5L, vo.getHeatmap().get(0).getCount());

        // categoryDist
        assertNotNull(vo.getCategoryDist());
        assertEquals(2, vo.getCategoryDist().size());

        // repairStats
        assertNotNull(vo.getRepairStats());
        assertEquals(1L, vo.getRepairStats().get(RepairStatus.PENDING.name()));

        // cards
        assertNotNull(vo.getCards());
        assertEquals(5L, vo.getCards().getTodayReservations());
        assertEquals(5L, vo.getCards().getPendingApprovals());
    }

    @Test
    void lab_admin_scope_passes_managed_lab_ids() {
        SecurityUserDetails ud = labAdmin();
        when(deviceMapper.selectList(any())).thenReturn(List.of(
                device(1L, "光谱仪", 100L, DeviceStatus.IDLE.name())));
        when(deviceCategoryMapper.selectList(any())).thenReturn(List.of());
        when(reservationItemMapper.selectOccupiedSlotCounts(any(), any(), any()))
                .thenReturn(List.of());
        when(reservationItemMapper.selectHeatmap(any(), any(), any(), anyInt()))
                .thenReturn(List.of());
        when(reservationMapper.selectDailyActiveTrendScoped(any(), any()))
                .thenReturn(List.of());
        when(repairReportMapper.selectList(any())).thenReturn(List.of());

        service.overview(ud, "device", 30);

        // LAB_ADMIN → 聚合查询传入自辖设备 id [1L]
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Long>> captor = ArgumentCaptor.forClass(List.class);
        verify(reservationItemMapper).selectOccupiedSlotCounts(captor.capture(), any(), any());
        assertEquals(List.of(1L), captor.getValue());
    }

    @Test
    void sys_admin_scope_no_lab_filter() {
        SecurityUserDetails ud = sysAdmin();
        when(deviceMapper.selectList(any())).thenReturn(List.of(
                device(1L, "光谱仪", 100L, DeviceStatus.IDLE.name())));
        when(deviceCategoryMapper.selectList(any())).thenReturn(List.of());
        when(reservationItemMapper.selectOccupiedSlotCounts(any(), any(), any()))
                .thenReturn(List.of());
        when(reservationItemMapper.selectHeatmap(any(), any(), any(), anyInt()))
                .thenReturn(List.of());
        when(reservationMapper.selectDailyActiveTrendScoped(any(), any()))
                .thenReturn(List.of());
        when(repairReportMapper.selectList(any())).thenReturn(List.of());

        service.overview(ud, "device", 30);

        // SYS_ADMIN → deviceIdsForQuery=null → 不加设备过滤
        verify(reservationItemMapper).selectOccupiedSlotCounts(isNull(), any(), any());
    }

    @Test
    void second_call_hits_redis_cache() {
        SecurityUserDetails ud = sysAdmin();
        when(deviceMapper.selectList(any())).thenReturn(List.of(
                device(1L, "光谱仪", 100L, DeviceStatus.IDLE.name())));
        when(deviceCategoryMapper.selectList(any())).thenReturn(List.of());
        when(reservationItemMapper.selectOccupiedSlotCounts(any(), any(), any()))
                .thenReturn(List.of(new OccupiedSlotCountVO(1L, 10L)));
        when(reservationItemMapper.selectHeatmap(any(), any(), any(), anyInt()))
                .thenReturn(List.of(new HeatmapCellVO(2, 9, 5L)));
        when(reservationMapper.selectDailyActiveTrendScoped(any(), any()))
                .thenReturn(List.of());
        when(repairReportMapper.selectList(any())).thenReturn(List.of());

        // 用 HashMap 模拟真实 Redis 缓存：第一次 miss → 计算 → 写缓存；第二次 hit → 跳过重算
        Map<String, String> cacheStore = new HashMap<>();
        when(valueOps.get(anyString())).thenAnswer(inv -> cacheStore.get(inv.getArgument(0)));
        doAnswer(inv -> {
            cacheStore.put(inv.getArgument(0), inv.getArgument(1));
            return null;
        }).when(valueOps).set(anyString(), anyString(), anyLong(), any(TimeUnit.class));

        // 第一次调用：cache miss → 计算并写缓存
        DashboardOverviewVO first = service.overview(ud, "device", 30);
        assertNotNull(first.getUtilization());
        assertFalse(first.getUtilization().isEmpty());

        // 第二次调用：cache hit → 跳过重 mapper
        DashboardOverviewVO second = service.overview(ud, "device", 30);
        assertEquals(first.getUtilization().size(), second.getUtilization().size());

        // 重 mapper 只被调用一次（第二次命中缓存未再调用）
        verify(reservationItemMapper, times(1)).selectOccupiedSlotCounts(any(), any(), any());
        verify(reservationItemMapper, times(1)).selectHeatmap(any(), any(), any(), anyInt());
    }

    @Test
    void me_returns_personal_stats() {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(7L);
        when(reservationMapper.selectList(any())).thenReturn(List.of());
        when(notificationMapper.selectCount(any())).thenReturn(3L);
        when(repairReportMapper.selectCount(any())).thenReturn(1L);

        DashboardMeVO vo = service.me(ud);

        assertNotNull(vo);
        assertEquals(3L, vo.getUnreadCount());
        assertEquals(1L, vo.getMyRepairCount());
        assertNotNull(vo.getMyReservationsByStatus());
        assertNotNull(vo.getMyTrend30d());
        assertEquals(30, vo.getMyTrend30d().size());
        assertNotNull(vo.getMyCategoryDist());
    }

    // ---------- 小工具 ----------

    private RepairReport repairReport(RepairStatus status) {
        RepairReport r = new RepairReport();
        r.setId(1L);
        r.setDeviceId(1L);
        r.setStatus(status.name());
        return r;
    }
}
