package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.Refill;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Per-user 速率限制(Bucket4j 内存版,8.x + redisson variant)。
 *
 * <p>默认 {@code ai.assistant.ratelimit.capacity = 20} token / 用户,
 * 每分钟补充 {@code refillPerMinute} token。每次 AI 调用扣 1。
 * 超限返回 {@code false},{@code AiAssistantService} 推 {@code RATE_LIMIT} 帧到客户端。
 *
 * <p>内存 {@link ConcurrentHashMap} 适合单实例部署;多实例需切到 Redis-backed bucket
 * (后续 Phase 可替换成 {@code bucket4j-redis-common} 包)。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Service
@RequiredArgsConstructor
public class RateLimitService {

    private final AiProperties props;
    private final ConcurrentHashMap<Long, Bucket> buckets = new ConcurrentHashMap<>();

    /**
     * 尝试为指定用户消费 1 个 token,返回是否允许通过。
     *
     * @param userId 当前登录用户 ID
     * @return true 可继续调用 LLM,false 被限流
     */
    public boolean tryConsume(Long userId) {
        return buckets.computeIfAbsent(userId, this::newBucket)
                .tryConsume(1);
    }

    private Bucket newBucket(Long userId) {
        AiProperties.RateLimit rl = props.getRatelimit();
        Bandwidth limit = Bandwidth.classic(
                rl.getCapacity(),
                Refill.intervally(rl.getRefillPerMinute(), Duration.ofMinutes(1))
        );
        return Bucket.builder().addLimit(limit).build();
    }
}
