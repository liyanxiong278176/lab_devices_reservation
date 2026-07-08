package com.lab.reservation.ai.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.mapper.AiToolExecutionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

/**
 * 工具执行审计 — 与 {@link ConfirmationService} 字段互补:
 * <ul>
 *   <li>ConfirmationService 维护状态机(可多步推进、合法转换校验)</li>
 *   <li>AuditService 仅做"已发生事件"的不可变记录(best-effort,失败不影响主流程)</li>
 * </ul>
 *
 * <p>实际生产中两者可以合并;当前分开是为了 Task 4 review 时可独立观察。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuditService {

    private final AiToolExecutionMapper mapper;
    private final ObjectMapper objectMapper;

    /**
     * 写入一条 pending 审计行 — 通常由外层编排器
     * (例如 AiAssistantService) 在调任何 AI tool 之前先调,
     * 失败 swallow 以免阻塞主链路。
     */
    public Long log(Long convId, Long messageId, String toolName, Object args) {
        AiToolExecution e = new AiToolExecution();
        e.setConversationId(convId);
        e.setMessageId(messageId);
        e.setToolName(toolName);
        e.setArguments(toJson(args));
        e.setStatus("pending");
        e.setCreatedAt(LocalDateTime.now());
        mapper.insert(e);
        return e.getId();
    }

    /** 推进审计行的 status + 写 result/errorMsg。如果记录不存在,silent skip。 */
    public void updateStatus(Long id, String status, Object result, String errorMsg) {
        AiToolExecution e = mapper.selectById(id);
        if (e == null) {
            return;
        }
        e.setStatus(status);
        if (result != null) {
            try {
                e.setResult(objectMapper.writeValueAsString(result));
            } catch (JsonProcessingException ex) {
                // swallow — audit best-effort
                log.warn("audit result serialize failed for id={}: {}", id, ex.toString());
            }
        }
        if (errorMsg != null) {
            e.setErrorMessage(errorMsg);
        }
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            log.warn("audit toJson failed: {}", e.toString());
            return "{}";
        }
    }
}
