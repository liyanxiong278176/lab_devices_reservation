package com.lab.reservation.ai.service;

import org.junit.jupiter.api.Test;
import org.springframework.ai.openai.api.OpenAiApi;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 锁定 {@link OpenAiApiFactory} 对「baseUrl 末段带 /vN」的路径覆盖行为。
 *
 * <p>Spring AI {@code OpenAiApi.Builder} 默认 {@code completionsPath=/v1/chat/completions},
 * 不解析 baseUrl 里的版本段,直拼 baseUrl + completionsPath。GLM 用 /v4,需要覆盖。
 *
 * <p>{@code OpenAiApi} 的 getter 是 package-private(同包外不可见),故用反射读字段锁行为,
 * 避免之后 Spring AI 升级改名时直接绕过。
 */
class OpenAiApiFactoryTest {

    private final OpenAiApiFactory factory = new OpenAiApiFactory();

    @Test
    void v4BaseUrlOverridesCompletionsPath() throws Exception {
        OpenAiApi api = factory.build("https://open.bigmodel.cn/api/paas/v4", "k");
        // GLM 服务路径就是 /v4/chat/completions,不能再叠 /v1
        assertEquals("https://open.bigmodel.cn/api/paas/v4", readField(api, "baseUrl"));
        assertEquals("/chat/completions", readField(api, "completionsPath"));
        assertEquals("/embeddings", readField(api, "embeddingsPath"));
    }

    @Test
    void plainBaseUrlKeepsDefaultV1Path() throws Exception {
        OpenAiApi api = factory.build("https://api.deepseek.com", "k");
        // deepseek/openai 等在 /v1/chat/completions,默认就行
        assertEquals("/v1/chat/completions", readField(api, "completionsPath"));
        assertEquals("/v1/embeddings", readField(api, "embeddingsPath"));
    }

    @Test
    void v1BaseUrlAlsoOverrides() throws Exception {
        // baseUrl 末尾 /v1 也按覆盖处理(实际 save 阶段 stripTrailingV1 已剥 /v1,
        // 这里验证 factory 对 /v\d+ 一视同仁,自身行为正确)。
        OpenAiApi api = factory.build("https://api.example.com/v1", "k");
        assertEquals("/chat/completions", readField(api, "completionsPath"));
    }

    private static Object readField(Object target, String name) throws Exception {
        java.lang.reflect.Field f = target.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(target);
    }
}