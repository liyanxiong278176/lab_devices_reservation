package com.lab.reservation.ai.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
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
                               Object... toolCallbacks) {
        return chatClient.prompt()
                .system(systemPrompt)
                .messages(history)
                .tools(toolCallbacks)
                .stream()
                .content();
    }

    /**
     * 熔断 / 网络 / 限流 fallback — 签名必须与 {@link #stream} 匹配(同参数 + Throwable)。
     * 返回错误 Flux,调用方 {@code .onErrorResume(...)} 会捕获并转成 AI_UNAVAILABLE 帧。
     */
    @SuppressWarnings("unused")
    public Flux<String> streamFallback(String systemPrompt,
                                       List<Message> history,
                                       Object[] toolCallbacks,
                                       Throwable t) {
        log.warn("SiliconFlow circuit breaker fallback triggered: {}", t.getMessage());
        return Flux.error(new BusinessException(ResultCode.AI_UNAVAILABLE));
    }
}
