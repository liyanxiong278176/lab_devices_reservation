package com.lab.reservation.ai.dto;

import java.util.List;
import java.util.Map;

/**
 * 服务端推送给 /user/{userId}/queue/assistant 的消息 union。
 *
 * <p>每个 record 对应 {@link com.lab.reservation.ai.service.AiFrameService#push}
 * 的 type 字段;{@code seq} 来自 Redis INCR 单调自增,客户端断线重连后
 * 可按 lastSeq 重放缺失帧。
 */
public sealed interface WsServerMsg {

    /** 流式 token chunk(assistant 正在打字)。 */
    record Delta(Long seq, Long convId, String text) implements WsServerMsg {}

    /** 步骤状态变化(started / completed / cancelled / failed)。 */
    record StepUpdate(Long seq, Long convId, int stepId, String status, String text, Long durationMs)
            implements WsServerMsg {}

    /** 快捷追问建议(可选,前端可用作 prompt chip)。 */
    record Suggestions(Long seq, Long convId, List<Map<String, String>> items)
            implements WsServerMsg {}

    /** 一轮对话结束(assistant 已落库);toolCalls 暂为空(Phase 后续填充)。 */
    record AssistantDone(Long seq, Long convId, String text, List<Map<String, Object>> toolCalls)
            implements WsServerMsg {}

    /** 写操作需要用户确认;前端弹窗后调 /app/assistant/confirm 或 /cancel。 */
    record ConfirmationRequired(Long seq, Long convId, Long actionId, String toolName,
                                String reason, String riskSummary, String estimatedImpact)
            implements WsServerMsg {}

    /** 写动作超时未确认,自动 cancel 后的通知。 */
    record ConfirmationExpired(Long seq, Long convId, Long actionId) implements WsServerMsg {}

    /** 写动作执行结果(用户确认后由后端异步推回)。 */
    record ExecutionResult(Long seq, Long convId, Long actionId, boolean ok, String code,
                           String msg, Object data) implements WsServerMsg {}

    /** 错误帧(code: RATE_LIMIT / AI_UNAVAILABLE / CONV_NOT_FOUND / ...)。 */
    record Error(Long seq, Long convId, String code, String msg) implements WsServerMsg {}

    /** 心跳(每 20s 一条,前端用来断线检测)。 */
    record Ping(Long seq, Long ts) implements WsServerMsg {}
}
