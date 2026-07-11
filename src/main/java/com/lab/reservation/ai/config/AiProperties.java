package com.lab.reservation.ai.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * AI 助手全局配置(限流 / 上下文 / RAG / pending 超时)。
 *
 * <p>对应 application*.yml 中 {@code ai.assistant.*} 节点。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@ConfigurationProperties(prefix = "ai.assistant")
public class AiProperties {

    /** 限流桶容量 / 每分钟补充速率。 */
    private RateLimit ratelimit = new RateLimit();

    /** 多轮对话上下文保留轮数(防止 token 爆)。 */
    private int contextWindowTurns = 10;

    /** 审批 pending 状态超过此分钟数未处理 → 自动取消。 */
    private int pendingTimeoutMinutes = 5;

    /**
     * pending 超时扫描间隔(ms),由 {@code AiActionTimeoutScheduler#fixedDelayString}
     * 占位符 {@code ${ai.assistant.pending-timeout-check-ms:60000}} 读取。
     * 默认 60000ms = 60s;同时在 yml 里可被覆盖无需改代码。
     */
    private long pendingTimeoutCheckMs = 60000L;

    /** RAG 检索参数。 */
    private Rag rag = new Rag();

    @Data
    public static class RateLimit {
        /** 桶容量(突发上限)。 */
        private int capacity = 30;
        /** 每分钟补充令牌数。 */
        private int refillPerMinute = 30;
    }

    @Data
    public static class Rag {
        /** 召回 top-K 文档数。 */
        private int topK = 5;
        /** 余弦相似度阈值,低于此值的 chunk 不注入 prompt。 */
        private double similarityThreshold = 0.6;
    }
}