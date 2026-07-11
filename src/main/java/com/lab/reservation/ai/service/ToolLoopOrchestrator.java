package com.lab.reservation.ai.service;

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
        // Task 5 实现 — 本 task 留空 stub,签名固定不要改
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
