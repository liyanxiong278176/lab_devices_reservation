package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
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
import com.lab.reservation.service.RecommendationService;
import com.lab.reservation.vo.recommendation.RecommendationItemVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 混合启发式推荐实现。
 *
 * <p>打分公式（权重来自 {@link RecommendProperties}）：
 * <pre>
 * Score(d,u) = α·categoryAffinity + β·labAffinity + γ·popularity + δ·tagMatch − ε·usedPenalty
 * </pre>
 *
 * <p>说明（采用的简化解释）：
 * <ul>
 *   <li>候选集：仅 {@code status = IDLE} 的设备（排除 MAINTENANCE/IN_USE，保证"现在可约"）。</li>
 *   <li>categoryAffinity / labAffinity：用户历史预约里该类目/实验室的占比（0..1）。无历史时为 0（自然冷启动）。</li>
 *   <li>tagMatch：设备 tags ∩ 用户偏好标签命中数 / 用户偏好标签总数（0..1）。偏好标签为历史设备标签的全集。</li>
 *   <li>popularity：近 30 天全站该设备被预约次数 / 全站最大值（0..1）。</li>
 *   <li>usedPenalty：用户在该设备上有活跃预约（PENDING/APPROVED/IN_USE）时扣 ε。</li>
 * </ul>
 *
 * <p>理由（reason）由加权后贡献最大的子分量决定，0.01 内的并列按
 * 类目 &gt; 实验室 &gt; 标签 &gt; 热门度 的优先级取舍以保持个性化语感。
 *
 * <p>结果按 {@code rec:u:{userId}} 缓存到 Redis（TTL 由配置决定），缓存的是
 * 完整排序结果（最多 {@value #MAX_CACHE_SIZE} 条），调用时按 limit 截断，保证不同 limit 复用同一缓存。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RecommendationServiceImpl implements RecommendationService {

    private static final String CACHE_KEY_PREFIX = "rec:u:";
    /** 理由取舍时视为并列的阈值 */
    private static final double REASON_TIE_EPS = 0.01;
    /** 缓存中保留的最大条数（截断上限） */
    private static final int MAX_CACHE_SIZE = 50;
    private static final int DEFAULT_LIMIT = 10;

    private final DeviceMapper deviceMapper;
    private final ReservationMapper reservationMapper;
    private final DeviceCategoryMapper deviceCategoryMapper;
    private final LabMapper labMapper;
    private final StringRedisTemplate stringRedisTemplate;
    private final ObjectMapper objectMapper;
    private final RecommendProperties recommendProperties;

    @Override
    public List<RecommendationItemVO> recommend(Long userId, int limit) {
        if (limit <= 0) {
            limit = DEFAULT_LIMIT;
        }
        List<RecommendationItemVO> ranked = getOrCompute(userId);
        int n = Math.min(limit, ranked.size());
        return new ArrayList<>(ranked.subList(0, n));
    }

    // ============================ 缓存读写 ============================

    private List<RecommendationItemVO> getOrCompute(Long userId) {
        String key = CACHE_KEY_PREFIX + userId;
        String cached = null;
        try {
            cached = stringRedisTemplate.opsForValue().get(key);
        } catch (Exception e) {
            log.warn("recommend cache read failed for {}: {}", key, e.getMessage());
        }
        if (cached != null) {
            try {
                return objectMapper.readValue(cached, new TypeReference<List<RecommendationItemVO>>() {});
            } catch (Exception e) {
                log.warn("recommend cache deserialize failed for {}: {}", key, e.getMessage());
            }
        }
        List<RecommendationItemVO> computed = compute(userId);
        try {
            stringRedisTemplate.opsForValue().set(key, objectMapper.writeValueAsString(computed),
                    recommendProperties.getCacheTtlMinutes() * 60L, TimeUnit.SECONDS);
        } catch (Exception e) {
            log.warn("recommend cache write failed for {}: {}", key, e.getMessage());
        }
        return computed;
    }

    // ============================ 打分核心 ============================

    private List<RecommendationItemVO> compute(Long userId) {
        RecommendProperties.Weights w = recommendProperties.getWeights();
        double alpha = w.getAlpha();
        double beta = w.getBeta();
        double gamma = w.getGamma();
        double delta = w.getDelta();
        double epsilon = w.getEpsilon();

        List<Device> allDevices = deviceMapper.selectList(null);
        if (allDevices == null || allDevices.isEmpty()) {
            return Collections.emptyList();
        }
        Map<Long, Device> deviceById = allDevices.stream()
                .collect(Collectors.toMap(Device::getId, d -> d, (a, b) -> a));

        Map<Long, String> catName = nameMap(deviceCategoryMapper.selectList(null),
                DeviceCategory::getId, DeviceCategory::getName);
        Map<Long, String> labName = nameMap(labMapper.selectList(null),
                Lab::getId, Lab::getName);

        // —— 用户历史 → 亲和度/偏好标签/活跃预约集合 ——
        List<Reservation> history = reservationMapper.selectList(
                new LambdaQueryWrapper<Reservation>().eq(Reservation::getUserId, userId));

        Map<Long, Integer> catCounts = new HashMap<>();
        Map<Long, Integer> labCounts = new HashMap<>();
        Map<String, Integer> tagFreq = new HashMap<>();
        Set<Long> activeDeviceIds = new HashSet<>();
        int total = 0;
        if (history != null) {
            for (Reservation r : history) {
                Device d = deviceById.get(r.getDeviceId());
                if (d == null) {
                    continue;
                }
                total++;
                if (d.getCategoryId() != null) {
                    catCounts.merge(d.getCategoryId(), 1, Integer::sum);
                }
                if (d.getLabId() != null) {
                    labCounts.merge(d.getLabId(), 1, Integer::sum);
                }
                if (d.getTags() != null) {
                    for (String t : d.getTags()) {
                        if (t != null) {
                            tagFreq.merge(t, 1, Integer::sum);
                        }
                    }
                }
                String st = r.getStatus();
                if ("PENDING".equals(st) || "APPROVED".equals(st) || "IN_USE".equals(st)) {
                    activeDeviceIds.add(r.getDeviceId());
                }
            }
        }
        Set<String> prefTags = tagFreq.keySet();
        int prefTagCount = prefTags.size();

        // —— 近 30 天全站预约 → 设备热门度 ——
        LocalDateTime since = LocalDateTime.now().minus(30, ChronoUnit.DAYS);
        List<Reservation> recent = reservationMapper.selectList(
                new LambdaQueryWrapper<Reservation>().ge(Reservation::getCreatedAt, since));
        Map<Long, Integer> popCounts = new HashMap<>();
        if (recent != null) {
            for (Reservation r : recent) {
                if (r.getDeviceId() != null) {
                    popCounts.merge(r.getDeviceId(), 1, Integer::sum);
                }
            }
        }
        int maxCount = popCounts.values().stream().max(Integer::compareTo).orElse(0);

        // —— 对每个候选设备打分 ——
        List<RecommendationItemVO> results = new ArrayList<>();
        for (Device d : allDevices) {
            if (!"IDLE".equals(d.getStatus())) {
                continue; // 仅推荐当前可约设备
            }
            double catRatio = (total > 0 && d.getCategoryId() != null)
                    ? catCounts.getOrDefault(d.getCategoryId(), 0) / (double) total : 0.0;
            double labRatio = (total > 0 && d.getLabId() != null)
                    ? labCounts.getOrDefault(d.getLabId(), 0) / (double) total : 0.0;
            double tagMatch = 0.0;
            if (prefTagCount > 0 && d.getTags() != null) {
                long hits = d.getTags().stream().filter(prefTags::contains).count();
                tagMatch = hits / (double) prefTagCount;
            }
            double normPop = maxCount > 0
                    ? popCounts.getOrDefault(d.getId(), 0) / (double) maxCount : 0.0;
            double penalty = activeDeviceIds.contains(d.getId()) ? epsilon : 0.0;

            double catContrib = alpha * catRatio;
            double labContrib = beta * labRatio;
            double popContrib = gamma * normPop;
            double tagContrib = delta * tagMatch;
            double score = catContrib + labContrib + popContrib + tagContrib - penalty;

            String catNm = catName.getOrDefault(d.getCategoryId(), "");
            String labNm = labName.getOrDefault(d.getLabId(), "");
            String reason = pickReason(catContrib, labContrib, tagContrib, popContrib, catNm, labNm);

            RecommendationItemVO vo = new RecommendationItemVO();
            vo.setDeviceId(d.getId());
            vo.setName(d.getName());
            vo.setCategoryId(d.getCategoryId());
            vo.setCategoryName(catNm);
            vo.setLabId(d.getLabId());
            vo.setLabName(labNm);
            vo.setScore(round4(score));
            vo.setReason(reason);
            vo.setBrand(d.getBrand());
            vo.setModel(d.getModel());
            vo.setStatus(d.getStatus());
            vo.setPricePerHour(d.getPricePerHour());
            results.add(vo);
        }

        results.sort(Comparator.comparingDouble(RecommendationItemVO::getScore).reversed()
                .thenComparing(RecommendationItemVO::getDeviceId));
        if (results.size() > MAX_CACHE_SIZE) {
            results = new ArrayList<>(results.subList(0, MAX_CACHE_SIZE));
        }
        return results;
    }

    /**
     * 选取理由：取加权贡献最大的子分量；并列（差距 ≤ {@link #REASON_TIE_EPS}）时按
     * 类目 &gt; 实验室 &gt; 标签 &gt; 热门度 优先。冷启动或全部为 0 时落到热门度。
     */
    private String pickReason(double cat, double lab, double tag, double pop,
                              String catName, String labName) {
        double best = Math.max(Math.max(cat, lab), Math.max(tag, pop));
        if (cat >= best - REASON_TIE_EPS && cat > 0) {
            return "因你常约【" + catName + "】类目";
        }
        if (lab >= best - REASON_TIE_EPS && lab > 0) {
            return "因你常用【" + labName + "】实验室";
        }
        if (tag >= best - REASON_TIE_EPS && tag > 0) {
            return "标签匹配你的偏好";
        }
        return "近30天热门设备";
    }

    private static double round4(double v) {
        return Math.round(v * 10000.0) / 10000.0;
    }

    private static <T> Map<Long, String> nameMap(List<T> list,
                                                 java.util.function.Function<T, Long> key,
                                                 java.util.function.Function<T, String> val) {
        if (list == null || list.isEmpty()) {
            return Collections.emptyMap();
        }
        return list.stream().collect(Collectors.toMap(key, val, (a, b) -> a));
    }
}
