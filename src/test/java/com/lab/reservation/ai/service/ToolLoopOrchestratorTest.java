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
import reactor.core.publisher.Flux;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
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

    private ChatResponse resp(String text) {
        return new ChatResponse(List.of(new Generation(new AssistantMessage(text))));
    }
}
