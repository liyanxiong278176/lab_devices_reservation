package com.lab.reservation.ai.service;

import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

import java.util.Map;

/**
 * AI 助手 WS 入口 — 瘦身委托层。
 *
 * <p>所有 LLM 调用 / 工具循环 / 写工具确认 / 流式收尾都委托给
 * {@link ToolLoopOrchestrator}。本类只负责:
 * <ol>
 *   <li>限流检查 ({@link RateLimitService})</li>
 *   <li>会话创建 / 校验 ({@link ConversationService})</li>
 *   <li>SecurityContext 注入(STOMP 线程不自动带 Authentication)</li>
 *   <li>BUSY 守卫(有挂起确认时拒绝新消息)</li>
 *   <li>per-user ChatClient 解析({@link UserChatClientProvider})</li>
 *   <li>持久化 user 消息 + 推 step_update 起步帧</li>
 * </ol>
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiAssistantService {

    private final ToolLoopOrchestrator orchestrator;
    private final ConversationService conversationService;
    private final AiFrameService frameService;
    private final RateLimitService rateLimitService;
    private final UserChatClientProvider userChatClientProvider;

    /**
     * 主入口:处理客户端 user 消息。
     *
     * <p>限流 → 会话创建/校验 → SecurityContext 注入 → BUSY 守卫 →
     * ChatClient 解析 → 持久化 user 消息 → step_update 起步 → 委托 orchestrator.runLoop。
     */
    public void handleUserMessage(SecurityUserDetails user, Long convIdIn, String text) {
        // 1. 限流
        if (!rateLimitService.tryConsume(user.getUserId())) {
            frameService.push(null, user, "error",
                    Map.of("code", "RATE_LIMIT", "msg", "AI 正在处理上一条消息,请稍候再发"));
            return;
        }

        // STOMP 入口的 Principal 不会自动写到 SecurityContextHolder;tool 内部用
        // SecurityContextHolder.getContext() 拿当前用户,所以需要显式塞进去。
        // 注意:setAuthentication 在下方 try 内部首行 — CONV_NOT_FOUND 在 try 外
        // return 时 setAuthentication 还没执行,context 仍 == prev,不会污染线程池。
        Authentication prev = SecurityContextHolder.getContext().getAuthentication();
        UsernamePasswordAuthenticationToken auth =
                new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities());

        // 2. 会话:null 新建,非 null 校验存在
        final Long convId;
        if (convIdIn == null) {
            convId = conversationService.create(user.getUserId()).getId();
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
            SecurityContextHolder.getContext().setAuthentication(auth);

            // 3. BUSY 守卫:有挂起的写工具确认时拒绝新消息
            if (orchestrator.isSuspended(convId)) {
                frameService.push(convId, user, "error",
                        Map.of("code", "BUSY", "msg", "有待确认操作,请先处理"));
                return;
            }

            // 4. per-user ChatClient:无 key → 提示去配置
            ChatClient cc = userChatClientProvider.resolve(user.getUserId()).orElse(null);
            if (cc == null) {
                frameService.push(convId, user, "error",
                        Map.of("code", "AI_NOT_CONFIGURED",
                               "msg", "请先配置你的 AI API Key",
                               "action", "open_settings"));
                return;
            }

            // 5. 持久化 user 消息(token 估算:中英文混合按 char/2 算下界)
            conversationService.appendMessage(convId, "user", text, null, text.length() / 2);

            // 6. step_update 起步 + 委托 orchestrator
            frameService.push(convId, user, "step_update",
                    Map.of("step_id", 0, "status", "started", "text", "正在处理您的请求"));
            orchestrator.runLoop(cc, user, convId, text);
        } finally {
            SecurityContextHolder.getContext().setAuthentication(prev);
        }
    }

    /** 用户确认执行某个待确认动作 → 委托 orchestrator.resumeFromConfirm。 */
    public void handleConfirm(SecurityUserDetails user, Long actionId) {
        Authentication prev = SecurityContextHolder.getContext().getAuthentication();
        try {
            SecurityContextHolder.getContext().setAuthentication(
                    new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
            ChatClient cc = userChatClientProvider.resolve(user.getUserId()).orElse(null);
            if (cc == null) {
                frameService.push(null, user, "error",
                        Map.of("code", "AI_NOT_CONFIGURED", "msg", "AI 未配置"));
                return;
            }
            orchestrator.resumeFromConfirm(cc, user, actionId);
        } finally {
            SecurityContextHolder.getContext().setAuthentication(prev);
        }
    }

    /** 用户取消某个待确认动作 → 委托 orchestrator.cancelAction。 */
    public void handleCancel(SecurityUserDetails user, Long actionId, Long convId) {
        orchestrator.cancelAction(user, actionId, convId);
    }

    /** 重连后按 lastSeq 重新拉取历史帧。 */
    public void handleResync(SecurityUserDetails user, Long convId, Long lastSeq) {
        frameService.resync(user, convId, lastSeq);
    }

    /** 用户主动中断当前会话的流式/loop 生成 → 委托 orchestrator.requestCancel。 */
    public void handleCancelSession(SecurityUserDetails user, Long convId) {
        orchestrator.requestCancel(convId, user);
    }
}
