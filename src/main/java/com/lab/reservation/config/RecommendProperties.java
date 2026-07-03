package com.lab.reservation.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 推荐算法配置，绑定 application-dev.yml 中 {@code lab.recommend.*}。
 *
 * <pre>
 * lab:
 *   recommend:
 *     weights: {alpha: 0.4, beta: 0.2, gamma: 0.25, delta: 0.1, epsilon: 0.3}
 *     cache-ttl-minutes: 5
 * </pre>
 */
@Data
@Component
@ConfigurationProperties(prefix = "lab.recommend")
public class RecommendProperties {

    /** 打分权重 */
    private Weights weights = new Weights();

    /** Redis 缓存 TTL（分钟） */
    private int cacheTtlMinutes = 5;

    @Data
    public static class Weights {
        /** 类目亲和度权重 α */
        private double alpha = 0.4;
        /** 实验室亲和度权重 β */
        private double beta = 0.2;
        /** 热门度权重 γ */
        private double gamma = 0.25;
        /** 标签匹配权重 δ */
        private double delta = 0.1;
        /** 已有活跃预约扣分权重 ε */
        private double epsilon = 0.3;
    }
}
