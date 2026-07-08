package com.lab.reservation.ai;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
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
@RestController
@RequestMapping("/api/ai")
public class HelloWorldController {

    private final ChatClient chatClient;

    public HelloWorldController(ChatClient.Builder builder) {
        this.chatClient = builder.build();
    }

    @PostMapping("/test")
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