package com.lab.reservation.ai.service;

import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * AiAssistantService 单元测试 — 验证瘦身后纯委托行为。
 *
 * <p>所有 5 个依赖 mock(orchestrator / conv / frame / rateLimit / provider),
 * 不依赖 Spring 上下文,无外部 IO。验证分支:限流 / 会话校验 / BUSY 守卫 /
 * AI 未配置 / SecurityContext 清理 / confirm+cancel 委托。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
class AiAssistantServiceTest {

    private ToolLoopOrchestrator orchestrator;
    private ConversationService conv;
    private AiFrameService frame;
    private RateLimitService rateLimit;
    private UserChatClientProvider provider;
    private ChatClient mockClient;
    private AiAssistantService svc;

    @BeforeEach
    void setUp() {
        SecurityContextHolder.clearContext();
        orchestrator = mock(ToolLoopOrchestrator.class);
        conv = mock(ConversationService.class);
        frame = mock(AiFrameService.class);
        rateLimit = mock(RateLimitService.class);
        provider = mock(UserChatClientProvider.class);
        mockClient = mock(ChatClient.class);
        svc = new AiAssistantService(orchestrator, conv, frame, rateLimit, provider);
    }

    private SecurityUserDetails student() {
        return new SecurityUserDetails(1L, "alice", "p", true, "Alice",
                List.of("STUDENT"), List.of());
    }

    private AiConversation newConv(long id) {
        AiConversation c = new AiConversation();
        c.setId(id);
        c.setUserId(1L);
        c.setCreatedAt(java.time.LocalDateTime.now());
        c.setUpdatedAt(java.time.LocalDateTime.now());
        return c;
    }

    // ------------------------------------------------------------------
    // handleUserMessage 分支
    // ------------------------------------------------------------------

    @Test
    void rate_limited_pushes_RATE_LIMIT_and_skips_orchestrator() {
        when(rateLimit.tryConsume(1L)).thenReturn(false);

        svc.handleUserMessage(student(), null, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(isNull(), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("RATE_LIMIT");
        verify(conv, never()).create(anyLong());
        verify(orchestrator, never()).runLoop(any(), any(), any(), any());
    }

    @Test
    void happy_path_delegates_runLoop_to_orchestrator() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.create(1L)).thenReturn(newConv(7L));
        when(provider.resolve(1L)).thenReturn(Optional.of(mockClient));

        svc.handleUserMessage(student(), null, "hello");

        verify(conv).create(1L);
        verify(conv).appendMessage(eq(7L), eq("user"), eq("hello"), isNull(), anyInt());
        verify(frame).push(eq(7L), any(), eq("step_update"), any());
        verify(orchestrator).runLoop(eq(mockClient), any(), eq(7L), eq("hello"));
    }

    @Test
    void existing_conv_skips_create_and_delegates() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(provider.resolve(1L)).thenReturn(Optional.of(mockClient));

        svc.handleUserMessage(student(), 42L, "hi");

        verify(conv, never()).create(anyLong());
        verify(orchestrator).runLoop(eq(mockClient), any(), eq(42L), eq("hi"));
    }

    @Test
    void conv_not_found_pushes_error_and_skips_orchestrator() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.getOrThrow(999L)).thenThrow(new RuntimeException("not found"));

        svc.handleUserMessage(student(), 999L, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(eq(999L), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("CONV_NOT_FOUND");
        verify(orchestrator, never()).runLoop(any(), any(), any(), any());
    }

    @Test
    void conv_not_found_restores_security_context() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.getOrThrow(999L)).thenThrow(new RuntimeException("not found"));
        Authentication sentinel = new org.springframework.security.authentication
                .UsernamePasswordAuthenticationToken("sentinel", null, List.of());
        SecurityContextHolder.getContext().setAuthentication(sentinel);

        svc.handleUserMessage(student(), 999L, "hi");

        // CONV_NOT_FOUND path: setAuthentication 在 try 内部,此 return 在 try 外部,
        // context 不应被污染。
        assertSame(sentinel, SecurityContextHolder.getContext().getAuthentication());
        SecurityContextHolder.clearContext();
    }

    @Test
    void busy_when_suspended_pushes_BUSY_and_skips_orchestrator() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.create(1L)).thenReturn(newConv(7L));
        when(orchestrator.isSuspended(7L)).thenReturn(true);

        svc.handleUserMessage(student(), null, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(eq(7L), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("BUSY");
        verify(orchestrator, never()).runLoop(any(), any(), any(), any());
    }

    @Test
    void ai_not_configured_pushes_error_and_skips_orchestrator() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.create(1L)).thenReturn(newConv(7L));
        when(provider.resolve(1L)).thenReturn(Optional.empty());

        svc.handleUserMessage(student(), null, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(eq(7L), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("AI_NOT_CONFIGURED");
        verify(conv, never()).appendMessage(eq(7L), anyString(), anyString(), isNull(), anyInt());
        verify(orchestrator, never()).runLoop(any(), any(), any(), any());
    }

    // ------------------------------------------------------------------
    // handleConfirm / handleCancel / handleCancelSession 委托
    // ------------------------------------------------------------------

    @Test
    void handleConfirm_delegates_resumeFromConfirm() {
        when(provider.resolve(1L)).thenReturn(Optional.of(mockClient));

        svc.handleConfirm(student(), 99L);

        verify(orchestrator).resumeFromConfirm(eq(mockClient), any(), eq(99L));
    }

    @Test
    void handleConfirm_ai_not_configured_pushes_error() {
        when(provider.resolve(1L)).thenReturn(Optional.empty());

        svc.handleConfirm(student(), 99L);

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(isNull(), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("AI_NOT_CONFIGURED");
        verify(orchestrator, never()).resumeFromConfirm(any(), any(), any());
    }

    @Test
    void handleCancel_delegates_cancelAction() {
        svc.handleCancel(student(), 55L, 7L);

        verify(orchestrator).cancelAction(any(), eq(55L), eq(7L));
    }

    @Test
    void handleCancelSession_delegates_requestCancel() {
        svc.handleCancelSession(student(), 7L);

        verify(orchestrator).requestCancel(eq(7L), any());
    }

    private static int anyInt() {
        return org.mockito.ArgumentMatchers.anyInt();
    }

    private static String anyString() {
        return org.mockito.ArgumentMatchers.anyString();
    }
}
