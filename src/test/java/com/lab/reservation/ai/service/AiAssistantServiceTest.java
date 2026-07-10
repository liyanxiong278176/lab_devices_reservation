package com.lab.reservation.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * AiAssistantService 单元测试 — 限流 / 会话创建 / cancel 三个核心分支。
 *
 * <p>全部 9 个依赖 mock,不依赖 Spring 上下文,无外部 IO。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
class AiAssistantServiceTest {

    private LlmClient llm;
    private ToolRegistry registry;
    private ConversationService conv;
    private ConfirmationService confirm;
    private AuditService audit;
    private AiFrameService frame;
    private RateLimitService rateLimit;
    private SystemPromptBuilder prompt;
    private UserChatClientProvider provider;
    private ChatClient mockClient;
    private AiAssistantService svc;

    @BeforeEach
    void setUp() {
        SecurityContextHolder.clearContext();
        llm = mock(LlmClient.class);
        registry = mock(ToolRegistry.class);
        conv = mock(ConversationService.class);
        confirm = mock(ConfirmationService.class);
        audit = mock(AuditService.class);
        frame = mock(AiFrameService.class);
        rateLimit = mock(RateLimitService.class);
        prompt = mock(SystemPromptBuilder.class);
        provider = mock(UserChatClientProvider.class);
        mockClient = mock(ChatClient.class);
        svc = new AiAssistantService(llm, registry, conv, confirm, audit, frame, rateLimit, prompt,
                new AiProperties(), new ObjectMapper(), provider);
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

    @Test
    void rate_limited_pushes_RATE_LIMIT_frame() {
        when(rateLimit.tryConsume(1L)).thenReturn(false);

        svc.handleUserMessage(student(), null, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(isNull(), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("RATE_LIMIT");
        verify(conv, never()).create(anyLong());
    }

    @Test
    void creates_conversation_when_null() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.create(1L)).thenReturn(newConv(7L));
        when(registry.availableFor(any())).thenReturn(List.of());
        when(conv.buildPrompt(anyLong(), anyString())).thenReturn(List.of());
        when(prompt.build(anyString(), anyLong())).thenReturn("system");
        when(provider.resolve(anyLong())).thenReturn(Optional.of(mockClient));
        when(llm.stream(anyString(), any(), any(ChatClient.class), any(ToolCallback[].class))).thenReturn(Flux.empty());

        svc.handleUserMessage(student(), null, "hi");

        verify(conv).create(1L);
        verify(conv).appendMessage(eq(7L), eq("user"), eq("hi"), isNull(), org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void not_configured_pushes_AI_NOT_CONFIGURED_frame() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.create(1L)).thenReturn(newConv(7L));
        when(provider.resolve(anyLong())).thenReturn(Optional.empty());

        svc.handleUserMessage(student(), null, "hi");

        ArgumentCaptor<Map<String, Object>> cap = ArgumentCaptor.forClass(Map.class);
        verify(frame).push(eq(7L), any(), eq("error"), cap.capture());
        assertThat(cap.getValue().get("code")).isEqualTo("AI_NOT_CONFIGURED");
        verify(conv, never()).appendMessage(eq(7L), anyString(), anyString(), isNull(), org.mockito.ArgumentMatchers.anyInt());
        verify(llm, never()).stream(anyString(), any(), any(ChatClient.class), any(ToolCallback[].class));
    }

    @Test
    void bad_conv_id_restores_security_context() {
        when(rateLimit.tryConsume(1L)).thenReturn(true);
        when(conv.getOrThrow(999L)).thenThrow(new RuntimeException("not found"));
        // seed the test thread's SecurityContext with a sentinel
        Authentication sentinel = new org.springframework.security.authentication
                .UsernamePasswordAuthenticationToken("sentinel", null, List.of());
        SecurityContextHolder.getContext().setAuthentication(sentinel);

        svc.handleUserMessage(student(), 999L, "hi");

        // CONV_NOT_FOUND path must NOT pollute: context unchanged (setAuthentication
        // has been moved inside try, so the try-outer return never ran it)
        assertSame(sentinel, SecurityContextHolder.getContext().getAuthentication());
        SecurityContextHolder.clearContext();
    }

    @Test
    void handleCancel_calls_confirmationService() {
        svc.handleCancel(student(), 42L);
        verify(confirm).cancel(42L);
    }
}
