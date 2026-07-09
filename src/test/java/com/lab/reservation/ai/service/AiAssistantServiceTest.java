package com.lab.reservation.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import reactor.core.publisher.Flux;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
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

    private SiliconFlowClient llm;
    private ToolRegistry registry;
    private ConversationService conv;
    private ConfirmationService confirm;
    private AuditService audit;
    private AiFrameService frame;
    private RateLimitService rateLimit;
    private SystemPromptBuilder prompt;
    private AiAssistantService svc;

    @BeforeEach
    void setUp() {
        llm = mock(SiliconFlowClient.class);
        registry = mock(ToolRegistry.class);
        conv = mock(ConversationService.class);
        confirm = mock(ConfirmationService.class);
        audit = mock(AuditService.class);
        frame = mock(AiFrameService.class);
        rateLimit = mock(RateLimitService.class);
        prompt = mock(SystemPromptBuilder.class);
        svc = new AiAssistantService(llm, registry, conv, confirm, audit, frame, rateLimit, prompt,
                new AiProperties(), new ObjectMapper());
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
        when(llm.stream(anyString(), any(), org.mockito.ArgumentMatchers.<org.springframework.ai.tool.ToolCallback>any())).thenReturn(Flux.empty());

        svc.handleUserMessage(student(), null, "hi");

        verify(conv).create(1L);
        verify(conv).appendMessage(eq(7L), eq("user"), eq("hi"), isNull(), org.mockito.ArgumentMatchers.anyInt());
    }

    @Test
    void handleCancel_calls_confirmationService() {
        svc.handleCancel(student(), 42L);
        verify(confirm).cancel(42L);
    }
}
