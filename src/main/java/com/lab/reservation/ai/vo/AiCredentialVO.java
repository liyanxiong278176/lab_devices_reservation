package com.lab.reservation.ai.vo;

import lombok.Data;

/**
 * 用户 LLM 凭证回显。{@code apiKeyMasked} 形如 {@code sk-****末4位},明文永不外泄。
 *
 * <p>未配置时仅 {@code configured=false},其余字段为 null,前端据此显空态引导。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Data
public class AiCredentialVO {
    private String provider;
    private String baseUrl;
    /** sk-****末4位,永不返明文 */
    private String apiKeyMasked;
    private String model;
    private Double temperature;
    /** 是否已配(前端据此显空态) */
    private boolean configured;
}
