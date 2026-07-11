package com.lab.reservation.ai.service;

import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.tool.ToolCallback;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ToolLoopOrchestratorTest {

    @Mock LlmClient llm;
    @Mock ToolRegistry registry;
    @Mock ToolCallbackResolver resolver;
    @Mock ConversationService conversationService;
    @Mock ConfirmationService confirmationService;
    @Mock AiFrameService frameService;
    @Mock SystemPromptBuilder promptBuilder;
    @Mock ChatClient chatClient;
    @Mock SecurityUserDetails user;

    ToolLoopOrchestrator orch;

    @BeforeEach
    void setup() {
        orch = new ToolLoopOrchestrator(llm, registry, resolver, conversationService,
                confirmationService, frameService, promptBuilder);
        when(user.getUserId()).thenReturn(1L);
        when(promptBuilder.build(any(), anyLong())).thenReturn("sys");
    }

    @Test
    void no_tool_calls_runs_phase2_streaming_and_pushes_done() {
        ChatResponse resp = resp("好的,这是我的回答");
        when(llm.callOnce(any(), anyList(), any(), anyList())).thenReturn(resp);
        when(llm.streamFinal(any(), anyList(), any())).thenReturn(Flux.just("好的", "这是"));
        when(conversationService.buildPrompt(anyLong())).thenReturn(List.of(new UserMessage("hi")));

        orch.runLoop(chatClient, user, 1L, "你好");

        // delta 帧每个 chunk 一次(streamFinal 桩返回 2 chunk → 2 次);只验证至少推过
        verify(frameService, atLeastOnce()).push(eq(1L), eq(user), eq("delta"), anyMap());
        verify(frameService).push(eq(1L), eq(user), eq("assistant_done"), anyMap());
        verify(conversationService).appendMessage(eq(1L), eq("assistant"), anyString(), any(), anyInt());
    }

    @Test
    void write_tool_suspends_and_pushes_confirmation_required_without_executing() {
        // LLM 第一轮决定调 createReservation(需确认)
        AssistantMessage am = new AssistantMessage("",
                Map.of(),
                List.of(new AssistantMessage.ToolCall("call_1", "function", "createReservation",
                        "{\"deviceId\":1,\"startTime\":\"2026-07-11T14:00:00\",\"endTime\":\"2026-07-11T16:00:00\"}")));
        when(llm.callOnce(any(), anyList(), any(), anyList()))
                .thenReturn(new ChatResponse(List.of(new Generation(am))));
        // findByName(orchestrator 在 Task 4 后用 findByName,不是 findById)
        when(registry.findByName("createReservation"))
                .thenReturn(Optional.of(confirmDef("createReservation")));
        when(resolver.resolve(user))
                .thenReturn(Map.of("createReservation", mock(ToolCallback.class)));
        when(conversationService.buildPrompt(anyLong()))
                .thenReturn(new ArrayList<>(List.of(new UserMessage("hi"))));

        orch.runLoop(chatClient, user, 1L, "帮我预约");

        // 创建 pending AiToolExecution + 推 confirmation_required 帧
        verify(confirmationService).create(eq(1L), any(), eq("createReservation"), anyMap());
        verify(frameService).push(eq(1L), eq(user), eq("confirmation_required"), anyMap());
        // dispatch 未触发(挂起);callback.call 没被调
        verify(frameService, never()).push(eq(1L), eq(user), eq("assistant_done"), anyMap());
        assertThat(orch.suspended).containsKey(1L);
    }

    private ChatResponse resp(String text) {
        return new ChatResponse(List.of(new Generation(new AssistantMessage(text))));
    }

    private ToolRegistry.ToolDefinition confirmDef(String name) {
        // record 的 accessor 是 final,default Mockito 不能 stub;直接构造真实实例更简洁
        return new ToolRegistry.ToolDefinition(
                name, null, null, name, "", Set.of(),
                true, "reason", "risk", "impact");
    }
}
