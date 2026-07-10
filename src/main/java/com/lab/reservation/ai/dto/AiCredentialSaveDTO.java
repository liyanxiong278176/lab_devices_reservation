package com.lab.reservation.ai.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 用户保存 / 更新 LLM 凭证的入参。
 *
 * <p>{@code baseUrl} 允许带尾部 {@code /v1},服务端会统一剥离后落库 + 测连。
 * {@code apiKey} 明文仅在本次请求内存活,test-before-persist 成功后只存密文。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Data
public class AiCredentialSaveDTO {
    /** deepseek / openai / siliconflow / custom */
    @NotBlank private String provider;
    @NotBlank private String baseUrl;
    @NotBlank private String apiKey;
    @NotBlank private String model;
    /** 可空:空时由 provider 用默认 0.3 */
    private Double temperature;
}
