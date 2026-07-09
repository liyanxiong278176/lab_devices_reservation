package com.lab.reservation.ai.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;

/**
 * 硅基流动调用包装 — 唯一有 {@code @CircuitBreaker} 拦截点的硅基流动出口。
 *
 * <p>重要:AOP 拦截要求 {@code @CircuitBreaker} 标记的方法必须被外部 bean 调用,
 * 不能放在 {@code @Bean} 工厂方法或 self-call 上。所以这里独立建一个 {@code @Service},
 * 由 {@code AiAssistantService} 调它的 {@link #stream(String, List, Object...)}。
 *
 * <p>fallback 触发条件:网络错误、API key 无效、模型不存在、429/5xx 等。
 * fallback 返回错误 Flux,主调用方通过 {@code .onErrorResume(...)} 捕获后
 * 转成 {@link ResultCode#AI_UNAVAILABLE} 帧推给前端。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
public class SiliconFlowClient {

    private final ChatClient chatClient;

    public SiliconFlowClient(ChatClient chatClient) {
        this.chatClient = chatClient;
    }

    /**
     * 流式调用硅基流动。被 {@code @CircuitBreaker} 拦截。
     *
     * @param systemPrompt  系统提示(由 {@link SystemPromptBuilder} 生成)
     * @param history       滑动窗口历史(由 {@link ConversationService#buildPrompt} 生成)
     * @param toolCallbacks 工具回调数组(由 {@link ToolRegistry} 提供的 Spring AI 形式)
     * @return 流式 token chunk
     */
    @CircuitBreaker(name = "siliconflow", fallbackMethod = "streamFallback")
    public Flux<String> stream(String systemPrompt,
                               List<Message> history,
                               ToolCallback... toolCallbacks) {
        // Spring AI 1.0.6 + OpenAI starter:用 .stream() 内部会触发
        // "Removing streamOptions from the request as it is not a streaming request"
        // 警告并退化成非流式 — tool callback + 1.0.6 chatClient.stream() 配合有问题。
        // 这里用 .call() 拿完整 reply,再以小 chunk 推到调用方,模拟流式断点体验。
        String reply = chatClient.prompt()
                .system(systemPrompt)
                .messages(history)
                .toolCallbacks(toolCallbacks)
                .call()
                .content();
        if (reply == null || reply.isEmpty()) {
            return Flux.empty();
        }
        // 按 12 字一块切,推给前端的 delta frame,触发打字机效果。
        java.util.List<String> chunks = new java.util.ArrayList<>();
        for (int i = 0; i < reply.length(); i += 12) {
            chunks.add(reply.substring(i, Math.min(i + 12, reply.length())));
        }
        return Flux.fromIterable(chunks);
    }

    /**
     * 熔断 / 网络 / 限流 fallback — 签名必须与 {@link #stream} 匹配(同参数 + Throwable)。
     * 返回错误 Flux,调用方 {@code .onErrorResume(...)} 会捕获并转成 AI_UNAVAILABLE 帧。
     */
    @SuppressWarnings("unused")
    public Flux<String> streamFallback(String systemPrompt,
                                       List<Message> history,
                                       ToolCallback[] toolCallbacks,
                                       Throwable t) {
        log.warn("SiliconFlow circuit breaker fallback triggered: {}", t.getMessage());
        return Flux.error(new BusinessException(ResultCode.AI_UNAVAILABLE));
    }
}
