package com.lab.reservation.ai.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Spring AI 1.0.6 自动装配只暴露 {@link ChatClient.Builder} bean;本工程需要
 * 一个共享 {@link ChatClient} 实例 — 因此显式 build() 一次作为 bean。
 *
 * <p>SiliconFlowClient(@CircuitBreaker 包裹点)和未来其它 LLM 调用方都注这个 bean。
 *
 * <p>注:这与 Task 1 的 HelloWorldController(自己调 builder.build())的设计是冲突的;
 * spec review 时已识别为 BLOCKING #1 — 此处统一 bean 收口,删除 Controller 内构造。
 */
@Configuration
public class ChatClientConfig {

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder.build();
    }
}
