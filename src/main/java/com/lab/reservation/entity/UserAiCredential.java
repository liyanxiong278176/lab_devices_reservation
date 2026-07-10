package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户 LLM 凭证(BYO-key)。一行 = 一用户一套 chat 配置。
 *
 * <p>{@code api_key_cipher} 由 {@link com.lab.reservation.ai.config.CryptoUtil} 加密,
 * 明文不出现在实体流转之外。{@code temperature} 为空时由 provider 用默认 0.3。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Data
@TableName("user_ai_credential")
public class UserAiCredential {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String provider;

    private String baseUrl;

    /** AES-GCM 密文(base64,IV 前置)。 */
    private String apiKeyCipher;

    private String model;

    private Double temperature;

    private Integer validated;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
