package com.lab.reservation.ai.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;

/**
 * LLM 调用出口 — 唯一 {@code @CircuitBreaker} 拦截点。
 *
 * <p>chat 不再 inject 单例 ChatClient;调用方(AiAssistantService 经
 * {@link UserChatClientProvider#resolve})传入 per-user ChatClient。
 * {@link #stream} 用 {@code .call()} 拿完整 reply 再 12 字 chunk 模拟流式
 * (Spring AI 1.0.6 {@code .stream()} 配合 tool callback 会退化成非流式并报警告)。
 * {@link #testConnection} 供 {@code AiCredentialService} 保存前验 key/model/base-url。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Slf4j
@Service
public class LlmClient {

    /**
     * 流式调用。被 {@code @CircuitBreaker(name="llm")} 拦截。
     *
     * @param chatClient 调用方传入的 per-user ChatClient(由 UserChatClientProvider 解析)
     */
    @CircuitBreaker(name = "llm", fallbackMethod = "streamFallback")
    public Flux<String> stream(String systemPrompt,
                               List<Message> history,
                               ChatClient chatClient,
                               ToolCallback... toolCallbacks) {
        String reply = chatClient.prompt()
                .system(systemPrompt)
                .messages(history)
                .toolCallbacks(toolCallbacks)
                .call()
                .content();
        if (reply == null || reply.isEmpty()) {
            return Flux.empty();
        }
        // 按 12 字一块切,推给前端 delta frame 触发打字机效果。
        List<String> chunks = new ArrayList<>();
        for (int i = 0; i < reply.length(); i += 12) {
            chunks.add(reply.substring(i, Math.min(i + 12, reply.length())));
        }
        return Flux.fromIterable(chunks);
    }

    /**
     * 熔断 / 网络 / 限流 fallback — 签名必须与 {@link #stream} 匹配(同参数 + 末尾 Throwable)。
     * 返回错误 Flux,调用方 {@code .onErrorResume(...)} 捕获后转成 AI_UNAVAILABLE 帧。
     */
    @SuppressWarnings("unused")
    public Flux<String> streamFallback(String systemPrompt,
                                       List<Message> history,
                                       ChatClient chatClient,
                                       ToolCallback[] toolCallbacks,
                                       Throwable t) {
        log.warn("LLM circuit breaker fallback triggered: {}", t.getMessage());
        return Flux.error(new BusinessException(ResultCode.AI_UNAVAILABLE));
    }

    /**
     * 保存前真连一次验 key/model/base-url。失败不抛,返回 false。
     */
    public boolean testConnection(String baseUrl, String apiKey, String model) {
        try {
            OpenAiApi api = OpenAiApi.builder().baseUrl(baseUrl).apiKey(apiKey).build();
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
