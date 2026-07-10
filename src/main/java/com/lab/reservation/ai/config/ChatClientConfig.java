package com.lab.reservation.ai.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Spring AI 1.0.6 自动装配只暴露 {@link ChatClient.Builder} bean;本工程需要
 * 一个共享 {@link ChatClient} 实例 — 因此显式 build() 一次作为 bean。
 *
 * <p>LlmClient(@CircuitBreaker 包裹点)和未来其它 LLM 调用方都注这个 bean(dev 兜底用)。
 *
 * <p>注:这与 Task 1 的 HelloWorldController(自己调 builder.build())的设计是冲突的;
 * spec review 时已识别为 BLOCKING #1 — 此处统一 bean 收口,删除 Controller 内构造。
 *
 * <p>条件化:复用 Spring AI 官方开关 {@code spring.ai.model.chat}(与 OpenAiChatAutoConfiguration
 * 同一属性)。dev 不设 → matchIfMissing=true → 建;prod 设 none → 跳过。
 * 用 {@code @ConditionalOnProperty} 而非 {@code @ConditionalOnBean(ChatClient.Builder.class)},
 * 因后者放在组件扫描的 bean 上在 Spring Boot 3.x 会命中条件求值时序 bug
 * (组件扫描阶段求值时,auto-config 的 ChatClient.Builder 定义尚未注册 → 误判)。
 */
@Configuration
public class ChatClientConfig {

    @Bean
    @ConditionalOnProperty(name = "spring.ai.model.chat", havingValue = "openai", matchIfMissing = true)
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder.build();
    }
}
