package com.lab.reservation.ai.service;

import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.ToolResponseMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 显式 agent 循环:callOnce(非流,internalToolExec 关)→ 手动 dispatch tool →
 * 写工具挂起推确认(Task 5)→ 用户确认 resume(Task 6)→ 无 toolCall 进 streamFinal 真流式收尾。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolLoopOrchestrator {

    static final int MAX_TURNS = 10;

    final LlmClient llm;
    final ToolRegistry registry;
    final ToolCallbackResolver resolver;
    final ConversationService conversationService;
    final ConfirmationService confirmationService;
    final AiFrameService frameService;
    final SystemPromptBuilder promptBuilder;

    /**
     * 默认配置(compact、无 indent)的 Jackson ObjectMapper — 用于把 args Map 序列化为
     * canonical JSON 字符串,以便与 {@link ConfirmationService#create} 内部
     * {@code toJson(args)} 的输出逐字节一致(argsHash 比对依赖此一致性)。
     */
    private static final com.fasterxml.jackson.databind.ObjectMapper CANONICAL_MAPPER =
            new com.fasterxml.jackson.databind.ObjectMapper();

    /** convId → 挂起的循环状态(写工具等确认)。in-memory,单实例。 */
    final Map<Long, SuspendState> suspended = new ConcurrentHashMap<>();
    /** convId → cancel flag。 */
    final Map<Long, AtomicBoolean> cancelFlags = new ConcurrentHashMap<>();

    public void runLoop(ChatClient cc, SecurityUserDetails user, Long convId, String text) {
        // text 已由 AiAssistantService 持久化;这里只从 DB 重建(防重复)
        List<Message> history = conversationService.buildPrompt(convId);
        runTurns(cc, user, convId, history, 0);
    }

    /** runLoop 与 resume(Task 6)共用的循环体(DRY)。 */
    void runTurns(ChatClient cc, SecurityUserDetails user, Long convId,
                  List<Message> history, int startTurn) {
        AtomicBoolean cancelled = cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false));
        if (startTurn == 0) {
            cancelled.set(false);
        }
        String sys = promptBuilder.build(SystemPromptBuilder.extractRole(user), user.getUserId());

        try {
            for (int turn = startTurn; turn < MAX_TURNS; turn++) {
                if (cancelled.get()) {
                    frameService.push(convId, user, "step_update",
                            Map.of("step_id", -1, "status", "cancelled", "text", "已取消"));
                    return;
                }
                Map<String, ToolCallback> cbMap = callbacksFor(user);
                ChatResponse resp = llm.callOnce(sys, history, cc, new ArrayList<>(cbMap.values()));
                AssistantMessage am = resp.getResult().getOutput();
                List<AssistantMessage.ToolCall> calls = am.getToolCalls() == null
                        ? List.of() : am.getToolCalls();

                // EMPTY_RESPONSE 守卫(熔断 fallback / 空答)
                if (calls.isEmpty()) {
                    String content = am.getText();
                    if (content == null || content.isBlank()) {
                        frameService.push(convId, user, "error",
                                Map.of("code", "EMPTY_RESPONSE", "msg", "AI 未返回内容"));
                        return;
                    }
                    // 阶段2 真流式收尾(content 丢弃,streamFinal 重新生成)
                    phase2(cc, convId, user, sys, history, cancelled);
                    return;
                }
                // MAX_TURNS 守卫
                if (turn == MAX_TURNS - 1 && !cancelled.get()) {
                    frameService.push(convId, user, "error",
                            Map.of("code", "TOO_MANY_TURNS", "msg", "工具调用轮次过多"));
                    return;
                }
                history.add(am); // 本轮 assistant(tool-calling)入 history

                for (AssistantMessage.ToolCall call : calls) {
                    ToolCallback cb = cbMap.get(call.name());
                    // 按 @Tool(name=...) 查 def(不是内部 id ClassName.methodName)
                    ToolRegistry.ToolDefinition def = registry.findByName(call.name()).orElse(null);
                    if (cb == null || def == null) {
                        history.add(toolResp(call.id(), call.name(), "{\"error\":\"unknown tool\"}"));
                        continue;
                    }
                    if (def.confirmRequired()) {
                        suspendForConfirm(convId, user, call, def, history, turn);  // Task 5 实现
                        return;
                    }
                    frameService.push(convId, user, "step_update",
                            Map.of("step_id", turn, "status", "running", "text", "执行 " + call.name()));
                    String result = dispatch(cb, call.arguments());
                    history.add(toolResp(call.id(), call.name(), result));
                }
                // 一轮 tool 调完,for 继续(让 LLM 看 tool 结果)
            }
        } finally {
            cancelFlags.remove(convId);
        }
    }

    /** 阶段2 真流式收尾。 */
    void phase2(ChatClient cc, Long convId, SecurityUserDetails user, String sys,
                List<Message> history, AtomicBoolean cancelled) {
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "started", "text", "正在生成回复"));
        StringBuilder reply = new StringBuilder();
        llm.streamFinal(sys, history, cc)
                .doOnNext(chunk -> {
                    if (cancelled.get()) return;
                    reply.append(chunk);
                    frameService.push(convId, user, "delta", Map.of("text", chunk));
                })
                .onErrorResume(err -> {
                    log.warn("streamFinal failed conv={}: {}", convId, err.getMessage());
                    frameService.push(convId, user, "error",
                            Map.of("code", "AI_UNAVAILABLE", "msg", "AI 助手暂时不可用"));
                    return Flux.empty();
                })
                .blockLast();
        String finalReply = reply.toString();
        if (!finalReply.isBlank()) {
            conversationService.appendMessage(convId, "assistant", finalReply, null, finalReply.length() / 2);
        }
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "completed", "text", "完成"));
        frameService.push(convId, user, "assistant_done",
                Map.of("text", finalReply, "tool_calls", List.of()));
        frameService.push(convId, user, "suggestions",
                Map.of("items", List.of(
                        Map.of("label", "查看我的预约", "value", "查看我的预约"),
                        Map.of("label", "推荐设备", "value", "推荐设备"))));
    }

    /** name → ToolCallback 映射(委托 resolver 测试缝)。 */
    Map<String, ToolCallback> callbacksFor(SecurityUserDetails user) {
        return resolver.resolve(user);
    }

    /** 用 Spring AI ToolCallback.call 执行 — 自动处理类型转换 + JSON 序列化。 */
    String dispatch(ToolCallback cb, String argsJson) {
        try {
            return cb.call(argsJson);
        } catch (Exception e) {
            log.warn("dispatch {} failed: {}", cb.getToolDefinition().name(), e.toString());
            return "{\"ok\":false,\"code\":\"TOOL_EXECUTION_FAILED\",\"msg\":\"" + e.getMessage() + "\"}";
        }
    }

    // Task 5 补:suspendForConfirm 实现
    void suspendForConfirm(Long convId, SecurityUserDetails user,
                           AssistantMessage.ToolCall call, ToolRegistry.ToolDefinition def,
                           List<Message> history, int turn) {
        Map<String, Object> args = parseArgs(call.arguments());
        // msgId 传 null:此时尚未把 assistant 消息落库(message 由 phase2/收尾统一落),
        // 审计行只靠 convId + toolName + args 定位即可
        Long actionId = confirmationService.create(convId, null, call.name(), args);
        // 关键:argsHash 必须基于 canonical JSON(与 create() 内部 toJson(args) 同一序列化
        // 形态),否则 LLM 原始 JSON 与 Jackson canonical 在空格/键序上的差异会触发假 ARGS_CHANGED。
        String argsHash = sha256(canonicalJson(args));

        suspended.put(convId, new SuspendState(turn, new ArrayList<>(history), call.id(), argsHash, user));

        frameService.push(convId, user, "step_update",
                Map.of("step_id", turn, "status", "awaiting_confirmation",
                        "text", "等待确认 " + call.name()));
        frameService.push(convId, user, "confirmation_required", Map.of(
                "action_id", actionId,
                "tool_name", call.name(),
                "reason", def.confirmReason(),
                "risk_summary", def.confirmRisk(),
                "estimated_impact", def.confirmImpact(),
                "args", args
        ));
        log.info("write tool {} suspended for conv={} actionId={}", call.name(), convId, actionId);
    }

    /**
     * 用户确认后恢复循环(Task 6):
     * <pre>
     *   1. confirmAndLoad 原子校验 owner + 推进 pending→confirmed
     *   2. 取 in-memory SuspendState,校验 args 哈希一致(防 TOCTOU)
     *   3. dispatch 写工具 → execute 落库 → execution_result 帧
     *   4. 把 ToolResponseMessage 追加进 history(LLM 续循环时能复述结果)
     *   5. 复用 runTurns 从挂起轮次续跑 → 无 toolCall 进 phase2
     * </pre>
     * SuspendState 丢失(重启 / 别实例)走 fallbackSingleExec:只执行 + 落库,无法续答。
     */
    public void resumeFromConfirm(ChatClient cc, SecurityUserDetails user, Long actionId) {
        AiToolExecution row = confirmationService.confirmAndLoad(actionId, user.getUserId());
        if (row == null) {
            frameService.push(null, user, "error",
                    Map.of("code", "FORBIDDEN", "msg", "无权操作或状态非法"));
            return;
        }
        SuspendState st = suspended.get(row.getConversationId());
        if (st == null) {
            fallbackSingleExec(cc, user, actionId, row);
            return;
        }
        if (!st.pendingArgsHash.equals(sha256(row.getArguments()))) {
            frameService.push(row.getConversationId(), user, "error",
                    Map.of("code", "ARGS_CHANGED", "msg", "确认参数已变化,请重新发起"));
            suspended.remove(row.getConversationId());
            return;
        }
        Map<String, ToolCallback> cbMap = callbacksFor(user);
        ToolCallback cb = cbMap.get(row.getToolName());
        if (cb == null) {
            confirmationService.error(actionId, "tool vanished");
            frameService.push(row.getConversationId(), user, "error",
                    Map.of("code", "TOOL_EXECUTION_FAILED", "msg", "工具已失效"));
            suspended.remove(row.getConversationId());
            return;
        }
        frameService.push(row.getConversationId(), user, "step_update",
                Map.of("status", "running", "text", "执行 " + row.getToolName()));
        String result = dispatch(cb, row.getArguments());
        confirmationService.execute(actionId, result);
        frameService.push(row.getConversationId(), user, "execution_result",
                Map.of("action_id", actionId, "ok", true, "result", result));

        // 关键:把确认的工具结果入 history,续循环时 LLM 才能准确复述
        st.history.add(toolResp(st.pendingCallId, row.getToolName(), result));
        suspended.remove(row.getConversationId());

        // 复用 runTurns 续跑(DRY):从 st.turn 起,history 已含 tool 结果
        runTurns(cc, user, row.getConversationId(), st.history, st.turn);
    }

    /** convId 是否挂起等确认 — 给 AiAssistantService 的 BUSY 守卫用(Task 10)。 */
    public boolean isSuspended(Long convId) {
        return suspended.containsKey(convId);
    }

    /**
     * 超时路径(Task 9):写工具确认 5min 未确认 → AiActionTimeoutScheduler 把行置 expired 后
     * 逐行调此方法。清 in-memory 挂起态(否则会话永久卡 BUSY)+ 推 {@code confirmation_expired}
     * 帧让前端关闭确认卡片。
     *
     * <p>userId 经 row → conversation 解析;解析失败(行不存在 / 会话查不到)仍清挂起态,
     * 只是 STOMP 不推(用户已不在线或数据完整性异常,pushByUser 内部 null userId 也不推)。
     */
    public void onExpire(Long convId, Long actionId) {
        suspended.remove(convId);
        AiToolExecution row = confirmationService.getRow(actionId);
        Long userId = null;
        if (row != null && row.getConversationId() != null) {
            try {
                userId = conversationService.getOrThrow(row.getConversationId()).getUserId();
            } catch (Exception ignore) {
                // 会话查不到 / 数据完整性异常:清挂起态已足够,不强推 STOMP
            }
        }
        frameService.pushByUser(convId, userId, "confirmation_expired",
                Map.of("action_id", actionId, "reason", "PENDING_TIMEOUT"));
        log.info("expired action {} conv {} suspended cleared", actionId, convId);
    }

    /**
     * 用户取消挂起的写工具确认(Task 7):
     * <pre>
     *   1. confirmationService.cancel 推 pending→cancelled(审计落库)
     *   2. 清 in-memory 挂起态
     *   3. 置 cancel flag,让任何 in-flight runTurns 迭代下一轮短路
     *   4. 推 execution_result 帧(ok=false, cancelled=true)给前端关闭 UI
     * </pre>
     */
    public void cancelAction(SecurityUserDetails user, Long actionId, Long convId) {
        confirmationService.cancel(actionId);
        suspended.remove(convId);
        // cancel flag set so any in-flight runTurns iteration short-circuits next turn
        cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false)).set(true);
        frameService.push(convId, user, "execution_result",
                Map.of("action_id", actionId, "ok", false, "cancelled", true));
    }

    /**
     * SuspendState 已丢(实例重启 / 横向扩容落到别的节点):尽力执行 + 落库,
     * 但无法把结果喂回 LLM 续答,只能推一条兜底文案。
     */
    void fallbackSingleExec(ChatClient cc, SecurityUserDetails user, Long actionId, AiToolExecution row) {
        Map<String, ToolCallback> cbMap = callbacksFor(user);
        ToolCallback cb = cbMap.get(row.getToolName());
        boolean ok = cb != null;
        String result = ok ? dispatch(cb, row.getArguments()) : "{\"error\":\"tool vanished\"}";
        confirmationService.execute(actionId, result);
        frameService.push(row.getConversationId(), user, "execution_result",
                Map.of("action_id", actionId, "ok", ok, "result", result));
        frameService.push(row.getConversationId(), user, "step_update",
                Map.of("status", "completed", "text", "完成"));
        frameService.push(row.getConversationId(), user, "assistant_done",
                Map.of("text", "操作已完成(会话上下文已失效,无法续答)", "tool_calls", List.of()));
    }

    /** 把 LLM 返的 tool arguments JSON 解成 Map(给 confirmationService.create 存参)。 */
    @SuppressWarnings("unchecked")
    static Map<String, Object> parseArgs(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
        } catch (Exception e) {
            log.warn("parseArgs failed for {}: {}", json, e.toString());
            return Map.of();
        }
    }

    /**
     * 把 args Map 序列化为 canonical JSON(默认配置 compact、无 indent)。
     * 与 {@link ConfirmationService#create} 内的 {@code toJson(args)} 输出逐字节一致 ——
     * 两侧 ObjectMapper 均为默认配置,parseArgs 保留 LinkedHashMap 插入序,键序稳定。
     * 用于 argsHash 计算,避免 LLM 原始 JSON 与 Jackson canonical 在空格/键序上的差异。
     */
    static String canonicalJson(Map<String, Object> args) {
        try {
            return CANONICAL_MAPPER.writeValueAsString(args);
        } catch (Exception e) {
            return "{}";
        }
    }

    static ToolResponseMessage toolResp(String id, String name, String data) {
        return new ToolResponseMessage(List.of(new ToolResponseMessage.ToolResponse(id, name, data)));
    }

    static String sha256(String s) {
        if (s == null) s = "";
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : h) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return String.valueOf(s.hashCode());
        }
    }

    /** 挂起态。 */
    static final class SuspendState {
        final int turn;
        final List<Message> history;
        final String pendingCallId;
        final String pendingArgsHash;
        final SecurityUserDetails user;
        SuspendState(int turn, List<Message> history, String pendingCallId,
                     String pendingArgsHash, SecurityUserDetails user) {
            this.turn = turn;
            this.history = history;
            this.pendingCallId = pendingCallId;
            this.pendingArgsHash = pendingArgsHash;
            this.user = user;
        }
    }
}
