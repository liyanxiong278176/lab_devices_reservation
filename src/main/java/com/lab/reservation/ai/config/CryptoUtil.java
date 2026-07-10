package com.lab.reservation.ai.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * AES-GCM 对称加解密 — 仅用于 user_ai_credential.api_key_cipher。
 *
 * <p>master key 走 env {@code AI_MASTER_KEY}(32 字节 base64)。每次加密随机 12B IV,
 * 前置于密文后整体 base64。解密失败返回 null(上层决定降级),不抛异常污染流程。
 *
 * <p>dev 缺 master key 时用固定派生值 + 启动 WARN,严禁 prod 缺 key 启动
 * (prod 通过 env 强制提供)。
 */
@Slf4j
@Component
public class CryptoUtil {

    private static final String TRANSFORM = "AES/GCM/NoPadding";
    private static final int IV_LEN = 12;
    private static final int TAG_BITS = 128;

    private final SecretKeySpec keySpec;

    public CryptoUtil(@Value("${ai.master-key:}") String masterKeyB64) {
        String b64 = (masterKeyB64 == null || masterKeyB64.isBlank())
                ? deriveDevKey() : masterKeyB64;
        if (masterKeyB64 == null || masterKeyB64.isBlank()) {
            log.warn("AI_MASTER_KEY 未配置,使用 dev 派生 key —— 仅限本地,生产必须配 env AI_MASTER_KEY");
        }
        byte[] raw = Base64.getDecoder().decode(b64);
        if (raw.length != 32) {
            throw new IllegalStateException("AI_MASTER_KEY 解码后必须 32 字节,实际 " + raw.length);
        }
        this.keySpec = new SecretKeySpec(raw, "AES");
    }

    public String encrypt(String plain) {
        if (plain == null) return null;
        try {
            byte[] iv = new byte[IV_LEN];
            java.security.SecureRandom.getInstanceStrong().nextBytes(iv);
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.ENCRYPT_MODE, keySpec, new GCMParameterSpec(TAG_BITS, iv));
            byte[] ct = c.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            ByteBuffer buf = ByteBuffer.allocate(iv.length + ct.length).put(iv).put(ct);
            return Base64.getEncoder().encodeToString(buf.array());
        } catch (Exception e) {
            throw new IllegalStateException("AES-GCM encrypt failed", e);
        }
    }

    public String decrypt(String cipherB64) {
        if (cipherB64 == null || cipherB64.isBlank()) return null;
        try {
            byte[] all = Base64.getDecoder().decode(cipherB64);
            ByteBuffer buf = ByteBuffer.wrap(all);
            byte[] iv = new byte[IV_LEN];
            buf.get(iv);
            byte[] ct = new byte[buf.remaining()];
            buf.get(ct);
            Cipher c = Cipher.getInstance(TRANSFORM);
            c.init(Cipher.DECRYPT_MODE, keySpec, new GCMParameterSpec(TAG_BITS, iv));
            return new String(c.doFinal(ct), StandardCharsets.UTF_8);
        } catch (Exception e) {
            log.warn("AES-GCM decrypt failed (returning null): {}", e.toString());
            return null;
        }
    }

    /** 明文 key 的稳定 hash,用作 cache 失效判定(不存明文)。 */
    public String keyHash(String plain) {
        return Integer.toHexString(java.util.Objects.hashCode(plain));
    }

    private static String deriveDevKey() {
        byte[] b = new byte[32];
        for (int i = 0; i < 32; i++) b[i] = (byte) ('d' + (i % 26));
        return Base64.getEncoder().encodeToString(b);
    }
}
