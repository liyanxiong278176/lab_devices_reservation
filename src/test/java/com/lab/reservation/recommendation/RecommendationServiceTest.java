package com.lab.reservation.recommendation;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.config.RecommendProperties;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.DeviceCategory;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.mapper.DeviceCategoryMapper;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.LabMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.impl.RecommendationServiceImpl;
import com.lab.reservation.vo.recommendation.RecommendationItemVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 推荐服务 TDD 单测：mock 三个 Mapper + StringRedisTemplate（用 Map 模拟 Redis 缓存），
 * 使用真实 {@link ObjectMapper} 与 {@link RecommendProperties}（默认权重）。
 *
 * <p>覆盖四类断言：类目亲和 Top1 + 理由；冷启动降级到热门度；MAINTENANCE 排除 & 活跃预约扣分；
 * 二次调用命中缓存跳过重算。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RecommendationServiceTest {

    @Mock private DeviceMapper deviceMapper;
    @Mock private ReservationMapper reservationMapper;
    @Mock private DeviceCategoryMapper deviceCategoryMapper;
    @Mock private LabMapper labMapper;
    @Mock private StringRedisTemplate stringRedisTemplate;
    @Mock private ValueOperations<String, String> valueOps;

    private RecommendationServiceImpl service;
    private final Map<String, String> cacheStore = new HashMap<>();

    private static final Long USER = 1L;
    private static final String KEY = "rec:u:1";

    @BeforeEach
    void setUp() {
        service = new RecommendationServiceImpl(
                deviceMapper, reservationMapper, deviceCategoryMapper, labMapper,
                stringRedisTemplate, new ObjectMapper(), new RecommendProperties());

        cacheStore.clear();
        lenient().when(stringRedisTemplate.opsForValue()).thenReturn(valueOps);
        // 用 Map 模拟 Redis：get 读 store，set 写 store
        lenient().when(valueOps.get(anyString())).thenAnswer(inv -> cacheStore.get(inv.getArgument(0)));
        lenient().doAnswer(inv -> {
            cacheStore.put(inv.getArgument(0), inv.getArgument(1));
            return null;
        }).when(valueOps).set(anyString(), anyString(), anyLong(), any(TimeUnit.class));
    }

    // ---------- 构造工具 ----------

    private Device device(Long id, String name, Long cat, Long lab, String status, String... tags) {
        Device d = new Device();
        d.setId(id);
        d.setName(name);
        d.setCategoryId(cat);
        d.setLabId(lab);
        d.setStatus(status);
        d.setTags(Arrays.asList(tags));
        d.setBrand("BrandX");
        d.setModel("ModelY");
        d.setPricePerHour(BigDecimal.TEN);
        return d;
    }

    private Reservation res(Long deviceId, Long userId, String status) {
        Reservation r = new Reservation();
        r.setDeviceId(deviceId);
        r.setUserId(userId);
        r.setStatus(status);
        r.setCreatedAt(LocalDateTime.now());
        return r;
    }

    private DeviceCategory cat(Long id, String name) {
        DeviceCategory c = new DeviceCategory();
        c.setId(id);
        c.setName(name);
        return c;
    }

    private Lab lab(Long id, String name) {
        Lab l = new Lab();
        l.setId(id);
        l.setName(name);
        return l;
    }

    // ---------- 测试 ----------

    /** 有历史且全部集中在"显微镜"类目 → Top1 属于该类目，理由含"常约"。 */
    @Test
    void history_user_top_is_affinity_category_with_reason() {
        // d1/d2 显微镜（IDLE），d3 光谱（IDLE，全站更热）
        List<Device> devices = Arrays.asList(
                device(1L, "显微镜A", 10L, 100L, "IDLE", "显微镜"),
                device(2L, "显微镜B", 10L, 100L, "IDLE", "显微镜"),
                device(3L, "光谱仪C", 20L, 200L, "IDLE", "光谱"));
        when(deviceMapper.selectList(any())).thenReturn(devices);
        when(deviceCategoryMapper.selectList(any()))
                .thenReturn(Arrays.asList(cat(10L, "显微镜"), cat(20L, "光谱")));
        when(labMapper.selectList(any()))
                .thenReturn(Arrays.asList(lab(100L, "物理实验室"), lab(200L, "化学实验室")));

        // 用户历史：两次预约都在类目 10（显微镜）
        List<Reservation> history = Arrays.asList(res(1L, USER, "COMPLETED"), res(2L, USER, "COMPLETED"));
        // 全站近 30 天：光谱仪 d3 最热（5 次）
        List<Reservation> recent = new ArrayList<>();
        for (int i = 0; i < 5; i++) {
            recent.add(res(3L, 999L, "COMPLETED"));
        }
        when(reservationMapper.selectList(any())).thenReturn(history, recent);

        List<RecommendationItemVO> result = service.recommend(USER, 10);

        assertFalse(result.isEmpty());
        RecommendationItemVO top = result.get(0);
        assertEquals(10L, top.getCategoryId());
        assertEquals("显微镜", top.getCategoryName());
        assertTrue(top.getReason().contains("常约"),
                "top reason should mention 常约, got: " + top.getReason());
    }

    /** 无历史 → 排序完全由热门度决定，理由统一为"近30天热门设备"。 */
    @Test
    void cold_start_user_degrades_to_popularity() {
        List<Device> devices = Arrays.asList(
                device(1L, "Dev1", 10L, 100L, "IDLE", "a"),
                device(2L, "Dev2", 10L, 100L, "IDLE", "b"),
                device(3L, "Dev3", 20L, 200L, "IDLE", "c"));
        when(deviceMapper.selectList(any())).thenReturn(devices);
        when(deviceCategoryMapper.selectList(any())).thenReturn(Collections.emptyList());
        when(labMapper.selectList(any())).thenReturn(Collections.emptyList());

        // 无历史
        List<Reservation> history = Collections.emptyList();
        // 近 30 天：d3 最热(5) > d2(2) > d1(1)
        List<Reservation> recent = new ArrayList<>();
        recent.add(res(1L, 999L, "COMPLETED"));
        recent.add(res(2L, 999L, "COMPLETED"));
        recent.add(res(2L, 999L, "COMPLETED"));
        for (int i = 0; i < 5; i++) {
            recent.add(res(3L, 999L, "COMPLETED"));
        }
        when(reservationMapper.selectList(any())).thenReturn(history, recent);

        List<RecommendationItemVO> result = service.recommend(USER, 10);

        assertEquals(3, result.size());
        // 按热门度降序
        assertEquals(3L, result.get(0).getDeviceId());
        assertEquals(2L, result.get(1).getDeviceId());
        assertEquals(1L, result.get(2).getDeviceId());
        // 冷启动理由统一
        for (RecommendationItemVO vo : result) {
            assertEquals("近30天热门设备", vo.getReason());
        }
    }

    /** MAINTENANCE 设备不出现在结果中；用户已有活跃预约的设备被扣分，排在同等条件的空闲设备之后。 */
    @Test
    void maintenance_device_excluded_and_active_reservation_penalized() {
        List<Device> devices = Arrays.asList(
                device(10L, "维修中", 10L, 100L, "MAINTENANCE", "x"),
                device(11L, "已预约", 10L, 100L, "IDLE", "显微镜"),
                device(12L, "空闲", 10L, 100L, "IDLE", "显微镜"));
        when(deviceMapper.selectList(any())).thenReturn(devices);
        when(deviceCategoryMapper.selectList(any())).thenReturn(Collections.singletonList(cat(10L, "显微镜")));
        when(labMapper.selectList(any())).thenReturn(Collections.singletonList(lab(100L, "物理实验室")));

        // 用户历史：对 d11 有一条 APPROVED 活跃预约 → 触发扣分
        List<Reservation> history = Collections.singletonList(res(11L, USER, "APPROVED"));
        // 近 30 天：d11 与 d12 热度相同（1 次）—— 控制变量，唯一差异是扣分
        List<Reservation> recent = Arrays.asList(res(11L, 999L, "COMPLETED"), res(12L, 999L, "COMPLETED"));
        when(reservationMapper.selectList(any())).thenReturn(history, recent);

        List<RecommendationItemVO> result = service.recommend(USER, 10);

        List<Long> ids = result.stream().map(RecommendationItemVO::getDeviceId).collect(Collectors.toList());
        assertFalse(ids.contains(10L), "MAINTENANCE device must be excluded");
        int idxActive = ids.indexOf(11L);
        int idxFree = ids.indexOf(12L);
        assertTrue(idxFree >= 0 && idxActive >= 0, "both IDLE devices should be present");
        assertTrue(idxFree < idxActive,
                "free device should rank above the one with an active reservation");
    }

    /** 第二次调用命中缓存 → 重算 mapper 不被再次查询。 */
    @Test
    void second_call_hits_cache() {
        List<Device> devices = Arrays.asList(
                device(1L, "Dev1", 10L, 100L, "IDLE", "a"),
                device(2L, "Dev2", 20L, 200L, "IDLE", "b"));
        when(deviceMapper.selectList(any())).thenReturn(devices);
        when(deviceCategoryMapper.selectList(any()))
                .thenReturn(Arrays.asList(cat(10L, "A"), cat(20L, "B")));
        when(labMapper.selectList(any())).thenReturn(Arrays.asList(lab(100L, "L1"), lab(200L, "L2")));
        when(reservationMapper.selectList(any()))
                .thenReturn(Collections.emptyList(), Arrays.asList(res(1L, 999L, "COMPLETED")));

        List<RecommendationItemVO> first = service.recommend(USER, 10);
        List<RecommendationItemVO> second = service.recommend(USER, 10);

        // 命中缓存：设备/类目/实验室 mapper 仅在首次计算时查询一次
        verify(deviceMapper, times(1)).selectList(any());
        verify(deviceCategoryMapper, times(1)).selectList(any());
        verify(labMapper, times(1)).selectList(any());
        // reservation 同样只在首次计算中被调用（历史 + 近 30 天共 2 次）
        verify(reservationMapper, times(2)).selectList(any());
        // 缓存已写入
        assertNotNull(cacheStore.get(KEY));
        // 两次返回等价
        assertEquals(first.size(), second.size());
        assertEquals(first.get(0).getDeviceId(), second.get(0).getDeviceId());
    }
}
