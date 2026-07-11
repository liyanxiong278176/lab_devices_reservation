package com.lab.reservation.ai.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.exception.ConfirmationException;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.mapper.AiToolExecutionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 写操作确认状态机:
 * <pre>
 *   pending → confirmed → executed
 *      │           │
 *      └────┬──────┴──────→ cancelled
 *           │
 *           └──────────────→ error
 *   (待确认 5 分钟后由 AiActionTimeoutScheduler 转为 expired)
 * </pre>
 *
 * <p>本服务只做状态推进 + 审计行写入;真正执行业务(如 reservationService.create)由
 * AiAssistantService 在用户发 confirm 帧时再调对应 tool 的真正 service — 这种
 * "状态机与执行解耦" 是为了让 WS 上 confirm/cancel 帧可以独立回放。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConfirmationService {

    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_CONFIRMED = "confirmed";
    public static final String STATUS_EXECUTED = "executed";
    public static final String STATUS_CANCELLED = "cancelled";
    public static final String STATUS_ERROR = "error";
    public static final String STATUS_EXPIRED = "expired";

    private final AiToolExecutionMapper mapper;
    private final ObjectMapper objectMapper;
    private final ConversationService conversationService;

    /**
     * 创建一条 pending 记录 — 通常由工具执行时(tool 收到 LLM 调用,但被
     * {@code @ConfirmRequired} 标记)在落库前调用。
     *
     * @return 新插入行的 id(自增主键)
     */
    public Long create(Long convId, Long msgId, String toolName, Map<String, Object> args) {
        AiToolExecution e = new AiToolExecution();
        e.setConversationId(convId);
        e.setMessageId(msgId);
        e.setToolName(toolName);
        e.setArguments(toJson(args));
        e.setStatus(STATUS_PENDING);
        e.setCreatedAt(LocalDateTime.now());
        mapper.insert(e);
        log.info("AI tool pending action created: id={} tool={} conv={}", e.getId(), toolName, convId);
        return e.getId();
    }

    /** 用户点确认:pending → confirmed。 */
    public void confirm(Long actionId) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) {
            throw new ConfirmationException("ACTION_NOT_FOUND", "action not found: " + actionId);
        }
        if (!STATUS_PENDING.equals(e.getStatus())) {
            throw new ConfirmationException(
                    "INVALID_STATE", "cannot confirm from status=" + e.getStatus());
        }
        e.setStatus(STATUS_CONFIRMED);
        e.setUserConfirmedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    /**
     * 原子地"校验属主 + 推进 pending→confirmed"并返回最新行;resume 路径(Task 6)用。
     *
     * <p>owner 解析:本表无 userId 列,经 {@code conversationId → AiConversation.userId} 间接比对。
     * 行不存在 / 非 pending / 会话不属于 requester 均返回 {@code null}(幂等 no-op,
     * 由调用方决定如何回应,通常是 silent 404)。注意:若会话本身不存在(数据完整性异常),
     * {@code conversationService.getOrThrow} 会抛 {@code BusinessException} 上浮 ——
     * 这是有意为之,真实异常不应被吞成 null。
     *
     * @param actionId        工具执行行 id
     * @param requesterUserId 当前发起 confirm 的用户 id
     * @return 已 confirmed 的行;校验失败返回 null
     */
    public AiToolExecution confirmAndLoad(Long actionId, Long requesterUserId) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) return null;
        if (!STATUS_PENDING.equals(e.getStatus())) return null;
        AiConversation conv = conversationService.getOrThrow(e.getConversationId());
        if (conv.getUserId() == null || !conv.getUserId().equals(requesterUserId)) return null;
        e.setStatus(STATUS_CONFIRMED);
        e.setUserConfirmedAt(LocalDateTime.now());
        mapper.updateById(e);
        return e;
    }

    /** 裸读一行(不做状态/属主校验);resume 路径在 confirmAndLoad 返回 null 时用于诊断。 */
    public AiToolExecution getRow(Long actionId) {
        return mapper.selectById(actionId);
    }

    /** 执行成功:confirmed → executed。 */
    public void execute(Long actionId, Object result) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) {
            throw new ConfirmationException("ACTION_NOT_FOUND", "action not found: " + actionId);
        }
        if (!STATUS_CONFIRMED.equals(e.getStatus())) {
            throw new ConfirmationException(
                    "INVALID_STATE", "cannot execute from status=" + e.getStatus());
        }
        e.setStatus(STATUS_EXECUTED);
        e.setResult(toJson(result));
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    /** 用户取消(仅 pending 可取消;其它状态 idempotent no-op)。 */
    public void cancel(Long actionId) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) {
            throw new ConfirmationException("ACTION_NOT_FOUND", "action not found: " + actionId);
        }
        if (!STATUS_PENDING.equals(e.getStatus())) {
            return; // idempotent
        }
        e.setStatus(STATUS_CANCELLED);
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    /** 执行失败:任意状态 → error(缺失行 silent skip;错误路径不容忍再抛异常)。 */
    public void error(Long actionId, String msg) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) return;
        e.setStatus(STATUS_ERROR);
        e.setErrorMessage(msg);
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    /**
     * 5 分钟超时批量将 pending 转为 expired(由 AiActionTimeoutScheduler 调)。
     *
     * <p>返回过期后的行(含 conversationId / id)而非单纯计数 — 调用方(scheduler)
     * 需逐行通知 {@code ToolLoopOrchestrator.onExpire} 清 in-memory 挂起态 + 推
     * {@code confirmation_expired} 帧。返回 List 而非 int 避免循环依赖:
     * ConfirmationService 不能反向依赖 Orchestrator。
     *
     * @param pendingTimeoutMinutes 阈值(分钟) — created_at 早于 now - 此值的 pending 才过期
     * @return 被置为 expired 的行(已 updateById,status=expired)
     */
    public List<AiToolExecution> expireOldPending(int pendingTimeoutMinutes) {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(pendingTimeoutMinutes);
        List<AiToolExecution> old = mapper.selectList(
                new QueryWrapper<AiToolExecution>()
                        .eq("status", STATUS_PENDING)
                        .lt("created_at", threshold)
        );
        old.forEach(e -> {
            e.setStatus(STATUS_EXPIRED);
            e.setErrorMessage("PENDING_TIMEOUT");
            mapper.updateById(e);
            log.info("AI action expired: id={}", e.getId());
        });
        return old;
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            log.warn("toJson failed: {}", e.toString());
            return "{}";
        }
    }
}
