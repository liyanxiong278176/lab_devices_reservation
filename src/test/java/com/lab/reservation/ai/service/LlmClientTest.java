package com.lab.reservation.ai.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Answers;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import reactor.core.publisher.Flux;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class LlmClientTest {

    @Mock(answer = Answers.RETURNS_DEEP_STUBS) ChatClient chatClient;

    LlmClient llm = new LlmClient();

    @Test
    void callOnce_returns_chatResponse() {
        AssistantMessage am = new AssistantMessage("hi");
        ChatResponse expected = new ChatResponse(List.of(new Generation(am)));
        when(chatClient.prompt().system(anyString()).messages(anyList()).options(any()).call().chatResponse())
                .thenReturn(expected);

        ChatResponse got = llm.callOnce("sys", List.of(new UserMessage("hi")), chatClient, List.of());

        assertThat(got).isSameAs(expected);
    }

    @Test
    void streamFinal_returns_flux_content() {
        when(chatClient.prompt().system(anyString()).messages(anyList()).stream().content())
                .thenReturn(Flux.just("a", "b", "c"));

        List<String> out = llm.streamFinal("sys", List.of(new UserMessage("hi")), chatClient).collectList().block();

        assertThat(out).containsExactly("a", "b", "c");
    }
}
