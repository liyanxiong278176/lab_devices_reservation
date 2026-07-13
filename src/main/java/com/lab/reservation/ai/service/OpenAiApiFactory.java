package com.lab.reservation.ai.service;

import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.stereotype.Component;

import java.util.regex.Pattern;

/**
 * 构造 {@link OpenAiApi} 的小工厂 — 集中处理「OpenAI 兼容协议但版本段在 baseUrl 里」的端点。
 *
 * <p>Spring AI 1.0.6 {@code OpenAiApi.Builder} 默认 {@code completionsPath=/v1/chat/completions},
 * {@code embeddingsPath=/v1/embeddings};builder 只接 {@code baseUrl(...)},不解析路径段,
 * 直接 baseUrl + completionsPath 拼最终 URL。
 *
 * <p>对绝大多数厂商(deepseek/openai/siliconflow/minimax)baseUrl 是
 * {@code https://api.xxx.com} 或 {@code https://api.xxx.com/v1} — 后者会被
 * {@code AiCredentialService.stripTrailingV1} 去掉,默认 /v1/chat/completions 正好对上。
 *
 * <p>GLM(智谱)不跟这套:baseUrl = {@code https://open.bigmodel.cn/api/paas/v4},端点
 * 路径是 {@code /v4/chat/completions},把默认 /v1 拼上去得到 {@code /v4/v1/chat/completions} → 404。
 * 检测到 baseUrl 末段是 {@code /v\d+} 就把 completionsPath / embeddingsPath 改成无版本前缀。
 *
 * <p>regex {@code /v\d+$} 仅匹配版本段(避免误伤 baseUrl 中间出现 /v1 的路径)。
 *
 * @author AI Assistant
 * @since 2026-07-13
 */
@Component
public class OpenAiApiFactory {

    /** 匹配 baseUrl 末段的版本号,如 {@code /v1} / {@code /v4}。 */
    private static final Pattern TRAILING_VERSION = Pattern.compile(".*/v\\d+$");

    public OpenAiApi build(String baseUrl, String apiKey) {
        OpenAiApi.Builder b = OpenAiApi.builder().baseUrl(baseUrl).apiKey(apiKey);
        if (TRAILING_VERSION.matcher(baseUrl).matches()) {
            // 用户已在 baseUrl 末尾给出版本段,builder 默认的 /v1/... 不能叠加
            b.completionsPath("/chat/completions").embeddingsPath("/embeddings");
        }
        return b.build();
    }
}