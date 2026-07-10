package com.lab.reservation.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.support.ToolCallbacks;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * AI 助手 while-loop 核心 — 调 LLM + 推帧 + cancel flag。
 *
 * <p>当前阶段实现读取类流式对话:每条 user 消息触发一次 LLM 调用,边输出边
 * 推 {@code delta} 帧;轮次结束推 {@code assistant_done} + {@code suggestions}。
 * 写操作(需要确认的工具调用)的 confirm 拦截留给后续 Phase — 框架已预留
 * {@link #handleConfirm} / {@link #handleCancel} 入口。
 *
 * <p>cancel flag 用 {@link ConcurrentHashMap} 按 convId 隔离;每次进入
 * {@link #handleUserMessage} 重置,finally 清理。{@code MAX_TURNS=10}
 * 防止工具循环调用失控。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiAssistantService {

    /** 单轮对话最大迭代次数(防工具循环失控);工具调用全开后实际只跑 1 轮。 */
    private static final int MAX_TURNS = 10;

    private final LlmClient llmClient;
    private final ToolRegistry toolRegistry;
    private final ConversationService conversationService;
    private final ConfirmationService confirmationService;
    private final AuditService auditService;
    private final AiFrameService frameService;
    private final RateLimitService rateLimitService;
    private final SystemPromptBuilder promptBuilder;
    private final AiProperties props;
    private final ObjectMapper objectMapper;
    private final UserChatClientProvider userChatClientProvider;

    /** convId → 是否已请求取消(下次 emit 时跳过 delta + break loop)。 */
    private final ConcurrentHashMap<Long, AtomicBoolean> cancelFlags = new ConcurrentHashMap<>();

    /**
     * 主入口:处理客户端 user 消息。
     * <ol>
     *   <li>限流检查</li>
     *   <li>会话创建或校验</li>
     *   <li>持久化 user 消息</li>
     *   <li>while-loop 调 LLM + 流式推 delta</li>
     *   <li>持久化 assistant 回复 + 推 done / suggestions</li>
     * </ol>
     */
    public void handleUserMessage(SecurityUserDetails user, Long convIdIn, String text) {
        // 1. 限流
        if (!rateLimitService.tryConsume(user.getUserId())) {
            frameService.push(null, user, "error",
                    Map.of("code", "RATE_LIMIT", "msg", "操作过于频繁,请稍后再试"));
            return;
        }

        // STOMP 入口的 Principal 不会自动写到 SecurityContextHolder;tool 内部用
        // SecurityContextHolder.getContext() 拿当前用户,所以需要显式塞进去,流式调用完
        // finally 清理,避免污染其他 inbound 线程。
        // 注意:setAuthentication 移到下方 try 内部首行 — 这样 CONV_NOT_FOUND 在 try 外
        // return 时 setAuthentication 还没执行,context 仍 == prev,不会污染线程池。
        org.springframework.security.core.Authentication prev =
                org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication();
        org.springframework.security.authentication.UsernamePasswordAuthenticationToken auth =
                new org.springframework.security.authentication.UsernamePasswordAuthenticationToken(
                        user, null, user.getAuthorities());

        // 2. 会话:null 新建,非 null 校验存在;用一个 final 引用,避免 lambda 闭包限制
        final Long convId;
        if (convIdIn == null) {
            AiConversation c = conversationService.create(user.getUserId());
            convId = c.getId();
        } else {
            try {
                conversationService.getOrThrow(convIdIn);
            } catch (Exception e) {
                frameService.push(convIdIn, user, "error",
                        Map.of("code", "CONV_NOT_FOUND", "msg", "会话不存在"));
                return;
            }
            convId = convIdIn;
        }

        try {
        // setAuthentication 放在 try 内部首行:所有 try 内的早返回(含 AI_NOT_CONFIGURED)
        // 都会命中 finally 恢复 prev;而 try 外的 CONV_NOT_FOUND 返回时这行还没执行,context 仍 == prev。
        org.springframework.security.core.context.SecurityContextHolder.getContext().setAuthentication(auth);

        // per-user ChatClient:无 key → 提示去配置(prod 严格拒绝,服务器零 chat key)
        ChatClient userChatClient = userChatClientProvider.resolve(user.getUserId()).orElse(null);
        if (userChatClient == null) {
            frameService.push(convId, user, "error",
                    Map.of("code", "AI_NOT_CONFIGURED",
                           "msg", "请先配置你的 AI API Key",
                           "action", "open_settings"));
            return;
        }

        // 3. step_update 起步
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "started", "text", "正在处理您的请求"));

        // 4. 持久化 user 消息(token 估算:中英文混合按 char/2 算下界)
        conversationService.appendMessage(convId, "user", text, null, estimateTokens(text));

        // 5. cancel flag(每个会话独立)
        AtomicBoolean cancelled = cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false));
        cancelled.set(false);

        for (int turn = 0; turn < MAX_TURNS; turn++) {
            if (cancelled.get()) {
                frameService.push(convId, user, "step_update",
                        Map.of("step_id", -1, "status", "cancelled", "text", "已取消"));
                break;
            }

            List<ToolRegistry.ToolDefinition> tools = toolRegistry.availableFor(user);
            // Spring AI 1.0.6 ChatClient 期待 ToolCallback[] 传 .toolCallbacks() (不是 .tools())。
            // MethodToolCallbackProvider 反射每个 bean 上的 @Tool 方法生成 ToolCallback 列表。
            Object[] beans = tools.stream().map(t -> t.bean()).distinct().toArray();
            org.springframework.ai.tool.ToolCallback[] toolCallbacks =
                    org.springframework.ai.tool.method.MethodToolCallbackProvider.builder()
                            .toolObjects(beans)
                            .build()
                            .getToolCallbacks();

            List<Message> history = conversationService.buildPrompt(convId, text);

            StringBuilder reply = new StringBuilder();
            long t0 = System.currentTimeMillis();
            llmClient.stream(
                    promptBuilder.build(SystemPromptBuilder.extractRole(user), user.getUserId()),
                    history,
                    userChatClient,
                    toolCallbacks
            ).doOnNext(chunk -> {
                // 取消后跳过 delta 推送
                if (cancelled.get()) return;
                reply.append(chunk);
                frameService.push(convId, user, "delta", Map.of("text", chunk));
            }).onErrorResume(err -> {
                log.warn("LLM stream failed for conv={}: {}", convId, err.getMessage());
                frameService.push(convId, user, "error",
                        Map.of("code", "AI_UNAVAILABLE", "msg", "AI 助手暂时不可用,请稍后再试"));
                return Flux.empty();
            }).blockLast();
            long costMs = System.currentTimeMillis() - t0;

            String finalReply = reply.toString();
            if (finalReply.isBlank()) break;

            // 持久化 assistant 回复
            conversationService.appendMessage(convId, "assistant", finalReply, null, estimateTokens(finalReply));

            // step_update 完成 + assistant_done + suggestions
            frameService.push(convId, user, "step_update",
                    Map.of("step_id", turn, "status", "completed",
                            "text", "本轮处理完成", "duration_ms", costMs));
            frameService.push(convId, user, "assistant_done",
                    Map.of("text", finalReply, "tool_calls", List.of()));
            frameService.push(convId, user, "suggestions",
                    Map.of("items", List.of(
                            Map.of("label", "查看我的预约", "value", "查看我的预约"),
                            Map.of("label", "推荐设备", "value", "推荐设备"))));
            // 当前阶段没接工具循环,1 轮后退出
            break;
        }
        } finally {
            cancelFlags.remove(convId);
            // 恢复 SecurityContext 到调用前的状态,避免污染后续 inbound 任务。
            org.springframework.security.core.context.SecurityContextHolder.getContext()
                    .setAuthentication(prev);
        }
    }

    /**
     * 用户确认执行某个待确认动作(占位 — 实际写工具执行留给后续 Phase,
     * 这里仅推进 ConfirmationService 内部状态;前端收到此 ack 后会自己调
     * 相应的 REST 端点拿到 ExecutionResult)。
     */
    public void handleConfirm(SecurityUserDetails user, Long actionId) {
        try {
            confirmationService.confirm(actionId);
        } catch (Exception e) {
            frameService.push(null, user, "error",
                    Map.of("code", "INVALID_STATE", "msg", e.getMessage()));
        }
    }

    /** 用户拒绝/取消某个待确认动作。 */
    public void handleCancel(SecurityUserDetails user, Long actionId) {
        confirmationService.cancel(actionId);
    }

    /** 重连后按 lastSeq 重新拉取历史帧。 */
    public void handleResync(SecurityUserDetails user, Long convId, Long lastSeq) {
        frameService.resync(user, convId, lastSeq);
    }

    /** 中断当前会话的流式生成。 */
    public void handleCancelSession(SecurityUserDetails user, Long convId) {
        cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false)).set(true);
        // 推一个 step_update cancelled 帧给前端,触发 store.state 走 cancelled 分支回到 idle。
        frameService.push(convId, user, "step_update",
                Map.of("step_id", -1, "status", "cancelled", "text", "已取消"));
        log.info("user {} cancelled session {}", user.getUserId(), convId);
    }

    // ------------------------------------------------------------------
    // 内部工具
    // ------------------------------------------------------------------

    /** 简单 token 估算:中英文混合按 length/2 算下界,空串给 0。 */
    private int estimateTokens(String s) {
        return s == null ? 0 : Math.max(1, s.length() / 2);
    }
}
