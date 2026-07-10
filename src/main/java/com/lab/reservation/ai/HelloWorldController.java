package com.lab.reservation.ai;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.aspect.Log;
import com.lab.reservation.security.SecurityUserDetails;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * 冒烟测试端点 — 验证 Spring AI + 硅基流动 连通性。
 *
 * <p>Phase A 完成后会保留作为 v1 debug / healthcheck 端点;
 * 生产环境可由 spring profile 或 {@code @ConditionalOnProperty} 关闭。
 *
 * <p>调用示例:
 * <pre>
 * curl -X POST http://localhost:8080/api/ai/test \
 *   -H "Authorization: Bearer ${TOKEN}" \
 *   -H "Content-Type: application/json" \
 *   -d '{"text":"你好,一句话介绍你自己"}'
 * </pre>
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Tag(name = "AI 助手")
@RestController
@RequestMapping("/ai")
@ConditionalOnProperty(name = "spring.ai.model.chat", havingValue = "openai", matchIfMissing = true)
public class HelloWorldController {

    private final ChatClient chatClient;

    /**
     * 显式构造器 + 单次 build():Spring AI 1.0.x 的 {@code ChatClientAutoConfiguration}
     * 只暴露 {@code ChatClient.Builder} bean(没有现成的 {@code ChatClient}),
     * 所以这里不能像其他 11 个 Controller 那样用 {@code @RequiredArgsConstructor}
     * 直接注入 {@code ChatClient},必须在构造期 {@code builder.build()} 一次。
     */
    public HelloWorldController(ChatClient.Builder builder) {
        this.chatClient = builder.build();
    }

    @Operation(summary = "AI 冒烟测试")
    @PostMapping("/test")
    @Log("AI 冒烟测试")
    public ToolExecutionResult test(
            @RequestBody Map<String, String> req,
            @AuthenticationPrincipal SecurityUserDetails user) {
        String text = req.getOrDefault("text", "你好,你能做什么?");

        long t0 = System.currentTimeMillis();
        String reply = chatClient.prompt()
                .user(text)
                .call()
                .content();
        long costMs = System.currentTimeMillis() - t0;
        log.info("[AI test] user={} costMs={} textLen={} replyLen={}",
                user == null ? "anonymous" : user.getUsername(),
                costMs, text.length(), reply == null ? 0 : reply.length());

        Map<String, Object> data = new HashMap<>();
        data.put("reply", reply);
        data.put("user", user == null ? "anonymous" : user.getUsername());
        data.put("costMs", costMs);
        return ToolExecutionResult.ok(data);
    }
}
