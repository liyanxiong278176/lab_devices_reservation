package com.lab.reservation.ai.service;

import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;

/**
 * LLM 调用出口 — 唯一 {@code @CircuitBreaker} 拦截点。
 *
 * <p>两阶段调用:
 * <ul>
 *   <li>{@link #callOnce} — 工具决策阶段。{@code internalToolExecutionEnabled=false}
 *       让模型只返回 toolCalls 不自动执行,编排器手动 dispatch + 拦截写工具确认。</li>
 *   <li>{@link #streamFinal} — 最终回答阶段。真流式,无 tools。</li>
 * </ul>
 *
 * <p>{@link #testConnection} 供 {@code AiCredentialService} 保存前验 key/model/base-url。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Slf4j
@Service
public class LlmClient {

    private final OpenAiApiFactory apiFactory;

    public LlmClient(OpenAiApiFactory apiFactory) {
        this.apiFactory = apiFactory;
    }

    /**
     * 阶段1:工具决策。{@code internalToolExecutionEnabled=false} 让模型只返回 toolCalls
     * 不自动执行,编排器手动 dispatch + 拦截写工具确认。
     */
    @CircuitBreaker(name = "llm", fallbackMethod = "callOnceFallback")
    public ChatResponse callOnce(String sys, List<Message> history,
                                 ChatClient cc, List<ToolCallback> tools) {
        OpenAiChatOptions opts = OpenAiChatOptions.builder()
                .toolCallbacks(tools)
                .internalToolExecutionEnabled(false)
                .build();
        return cc.prompt()
                .system(sys)
                .messages(history)
                .options(opts)
                .call()
                .chatResponse();
    }

    /**
     * 熔断 fallback:返合成 ChatResponse,含一条空内容 AssistantMessage(无 toolCalls)。
     * 编排器 runTurns 见 calls 空 + content 空 → 走 EMPTY_RESPONSE 错误分支。
     * 注意:不能返 new ChatResponse(List.of()) — getResult() 会返 null,runTurns 的
     * resp.getResult().getOutput() 直接 NPE,error 帧推不出去,前端卡死。
     */
    @SuppressWarnings("unused")
    public ChatResponse callOnceFallback(String sys, List<Message> history,
                                         ChatClient cc, List<ToolCallback> tools, Throwable t) {
        log.warn("LLM callOnce fallback: {}", t.getMessage());
        return new ChatResponse(List.of(new Generation(new AssistantMessage(""))));
    }

    /**
     * 阶段2:最终回答。真流式,无 tools。
     */
    public Flux<String> streamFinal(String sys, List<Message> history, ChatClient cc) {
        return cc.prompt()
                .system(sys)
                .messages(history)
                .stream()
                .content();
    }

    /**
     * 保存前真连一次验 key/model/base-url。失败不抛,返回 false。
     */
    public boolean testConnection(String baseUrl, String apiKey, String model) {
        try {
            OpenAiApi api = apiFactory.build(baseUrl, apiKey);
            OpenAiChatOptions opt = OpenAiChatOptions.builder().model(model).build();
            OpenAiChatModel m = OpenAiChatModel.builder().openAiApi(api).defaultOptions(opt).build();
            String reply = ChatClient.create(m).prompt().user("hi").call().content();
            return reply != null && !reply.isBlank();
        } catch (Exception e) {
            log.warn("LLM testConnection failed for base={} model={}: {}", baseUrl, model, e.toString());
            return false;
        }
    }
}
