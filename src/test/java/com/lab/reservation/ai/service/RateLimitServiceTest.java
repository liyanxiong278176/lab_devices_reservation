package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RateLimitService 单元测试 — 验证默认配置(20 token / 用户)桶耗尽行为。
 */
class RateLimitServiceTest {

    @Test
    void tryConsume_returns_true_within_capacity() {
        AiProperties props = new AiProperties();
        RateLimitService svc = new RateLimitService(props);
        for (int i = 0; i < 20; i++) {
            assertThat(svc.tryConsume(1L)).isTrue();
        }
    }

    @Test
    void tryConsume_returns_false_after_capacity_exhausted() {
        AiProperties props = new AiProperties();
        RateLimitService svc = new RateLimitService(props);
        for (int i = 0; i < 20; i++) {
            svc.tryConsume(2L);
        }
        assertThat(svc.tryConsume(2L)).isFalse();
    }

    @Test
    void buckets_are_per_user_independent() {
        AiProperties props = new AiProperties();
        RateLimitService svc = new RateLimitService(props);
        // user 1 用完
        for (int i = 0; i < 20; i++) {
            svc.tryConsume(1L);
        }
        assertThat(svc.tryConsume(1L)).isFalse();
        // user 2 全新桶
        assertThat(svc.tryConsume(2L)).isTrue();
    }
}
