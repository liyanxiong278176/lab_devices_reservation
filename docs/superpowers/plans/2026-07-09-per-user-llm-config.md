# 每用户 LLM Key(BYO)+ 零 Key 启动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每个用户在「个人中心 → AI 助手配置」填自己的 chat API key(加密存 DB),服务器零 chat key,应用零 AI key 也能正常启动;RAG(embedding)保留系统级可选;本地 dev 用 yml 兜底。

**Architecture:** chat 走 per-user 运行时 `ChatClient`(`UserChatClientProvider` 按 userId 缓存构建),取代启动单例 bean;prod 排除 `OpenAiChatAutoConfiguration` 使零 key 启动;embedding 走 env 系统级 + `@ConditionalOnBean` 可选;`SiliconFlowClient` 重命名 `LlmClient` 收 `ChatClient` 参数;key 用 AES-GCM(`CryptoUtil` + env master key)加密落库。

**Tech Stack:** Spring Boot 3.2.5 / Spring AI 1.0.6(OpenAI 兼容 starter)/ MyBatis-Plus / Flyway / Resilience4j / Vue 3 + Pinia + Element Plus / vitest。

**Spec:** `docs/superpowers/specs/2026-07-09-per-user-llm-config-design.md`

---

## File Structure

### 新建(后端)
- `src/main/resources/db/migration/V7__user_ai_credential.sql` — 建表
- `src/main/java/com/lab/reservation/entity/UserAiCredential.java` — 实体
- `src/main/java/com/lab/reservation/mapper/UserAiCredentialMapper.java` — BaseMapper
- `src/main/java/com/lab/reservation/ai/config/CryptoUtil.java` — AES-GCM 加解密
- `src/main/java/com/lab/reservation/ai/service/AiCredentialService.java` — CRUD + test-call + /v1 strip
- `src/main/java/com/lab/reservation/ai/service/UserChatClientProvider.java` — per-user 缓存工厂
- `src/main/java/com/lab/reservation/ai/controller/AiCredentialController.java` — REST
- `src/main/java/com/lab/reservation/ai/dto/AiCredentialSaveDTO.java` — 入参
- `src/main/java/com/lab/reservation/ai/vo/AiCredentialVO.java` — 出参(key masked)

### 修改(后端)
- `src/main/java/com/lab/reservation/ai/service/SiliconFlowClient.java` → **重命名** `LlmClient.java`,签名加 `ChatClient`
- `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java` — resolve + AI_NOT_CONFIGURED 帧
- `src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java` — `@ConditionalOnBean`
- `src/main/resources/application.yml` — 接收从 siliconflow yml 迁出的非密配置(ai.assistant/chroma/resilience4j)
- `src/main/resources/application-siliconflow.yml` — 只留密钥(chat 兜底 + embedding)
- `src/main/resources/application-prod.yml` — `spring.autoconfigure.exclude` + embedding env 占位
- `src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java` — mock 签名
- 新测试:`CryptoUtilTest`、`UserChatClientProviderTest`、`AiCredentialServiceTest`

### 新建(前端)
- `frontend/src/types/aiConfig.ts`、`frontend/src/api/aiCredential.ts`、`frontend/src/stores/aiConfig.ts`、`frontend/src/views/user/AiConfig.vue`

### 修改(前端)
- 个人中心视图(定位:`frontend/src/views/user/` 下的 Profile/Settings 页)加 tab
- `frontend/src/stores/ai.ts` — `AI_NOT_CONFIGURED` 分支
- `frontend/src/components/ai/AiAssistant.vue` — 「去配置」按钮
- `frontend/src/types/ai.ts` — error 带 `action` 字段

### 部署
- `docker-compose.prod.yml` — `env_file: .env`
- `.env.example`(tracked 模板,不含真值)

---

## Task 1: CryptoUtil(AES-GCM 加解密)

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/config/CryptoUtil.java`
- Test: `src/test/java/com/lab/reservation/ai/config/CryptoUtilTest.java`

- [ ] **Step 1: 写失败测试**

`src/test/java/com/lab/reservation/ai/config/CryptoUtilTest.java`:
```java
package com.lab.reservation.ai.config;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CryptoUtilTest {

    private final CryptoUtil util = new CryptoUtil("dGVzdC1tYXN0ZXIta2V5LTMyLWJ5dGVzLWxvbmctYWFhYQ=="); // 32B base64

    @Test
    void encryptDecryptRoundTrip() {
        String plain = "sk-abcdef123456";
        String cipher = util.encrypt(plain);
        assertNotEquals(plain, cipher);
        assertEquals(plain, util.decrypt(cipher));
    }

    @Test
    void eachEncryptionUsesFreshIv() {
        String plain = "sk-same";
        assertNotEquals(util.encrypt(plain), util.encrypt(plain));
    }

    @Test
    void decryptGarbageReturnsNull() {
        assertNull(util.decrypt("not-valid-base64!!!"));
    }
}
```

- [ ] **Step 2: 跑测试验证失败**

Run: `mvn test -Dtest=CryptoUtilTest`
Expected: FAIL — `CryptoUtil` 类不存在(编译错)。

- [ ] **Step 3: 实现 CryptoUtil**

`src/main/java/com/lab/reservation/ai/config/CryptoUtil.java`:
```java
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
```

- [ ] **Step 4: 跑测试验证通过**

Run: `mvn test -Dtest=CryptoUtilTest`
Expected: PASS(3 个测试绿)。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/config/CryptoUtil.java src/test/java/com/lab/reservation/ai/config/CryptoUtilTest.java
git commit -m "feat(ai): add AES-GCM CryptoUtil for user key encryption"
```

---

## Task 2: V7 迁移 + 实体 + Mapper

**Files:**
- Create: `src/main/resources/db/migration/V7__user_ai_credential.sql`
- Create: `src/main/java/com/lab/reservation/entity/UserAiCredential.java`
- Create: `src/main/java/com/lab/reservation/mapper/UserAiCredentialMapper.java`

- [ ] **Step 1: 写迁移脚本**

`src/main/resources/db/migration/V7__user_ai_credential.sql`:
```sql
-- 每用户自带 LLM chat 配置(BYO-key)。api_key 只存 AES-GCM 密文。
-- user_id 唯一:一用户一套 chat 配置。
CREATE TABLE IF NOT EXISTS user_ai_credential (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  user_id         BIGINT       NOT NULL,
  provider        VARCHAR(32)  NOT NULL COMMENT 'deepseek/openai/siliconflow/custom',
  base_url        VARCHAR(255) NOT NULL,
  api_key_cipher  TEXT         NOT NULL COMMENT 'AES-GCM 密文(IV 前置),明文永不落库',
  model           VARCHAR(64)  NOT NULL,
  temperature     DOUBLE       NULL     COMMENT '可空,代码默认 0.3',
  validated       TINYINT      NOT NULL DEFAULT 1 COMMENT 'test-before-persist 决定恒为 1',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_ai_credential (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户 LLM 凭证(BYO-key)';
```

- [ ] **Step 2: 写实体**

`src/main/java/com/lab/reservation/entity/UserAiCredential.java`:
```java
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
```

- [ ] **Step 3: 写 Mapper**

`src/main/java/com/lab/reservation/mapper/UserAiCredentialMapper.java`:
```java
package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.UserAiCredential;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserAiCredentialMapper extends BaseMapper<UserAiCredential> {
}
```

- [ ] **Step 4: 启动验证迁移生效**

Run: `mvn spring-boot:run -DskipTests -Dspring-boot.run.profiles=siliconflow,dev`(本地有 mysql+redis)
Expected: 启动日志 Flyway `Migrating schema ... to version "7 - user ai credential"`;`SHOW TABLES LIKE 'user_ai_credential'` 命中。Ctrl+C 停。

- [ ] **Step 5: Commit**

```bash
git add src/main/resources/db/migration/V7__user_ai_credential.sql src/main/java/com/lab/reservation/entity/UserAiCredential.java src/main/java/com/lab/reservation/mapper/UserAiCredentialMapper.java
git commit -m "feat(ai): add V7 user_ai_credential table + entity + mapper"
```

---

## Task 3: AiCredentialService(CRUD + test-call + /v1 strip)

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/dto/AiCredentialSaveDTO.java`
- Create: `src/main/java/com/lab/reservation/ai/vo/AiCredentialVO.java`
- Create: `src/main/java/com/lab/reservation/ai/service/AiCredentialService.java`
- Test: `src/test/java/com/lab/reservation/ai/service/AiCredentialServiceTest.java`

- [ ] **Step 1: DTO + VO**

`src/main/java/com/lab/reservation/ai/dto/AiCredentialSaveDTO.java`:
```java
package com.lab.reservation.ai.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class AiCredentialSaveDTO {
    @NotBlank private String provider;   // deepseek/openai/siliconflow/custom
    @NotBlank private String baseUrl;
    @NotBlank private String apiKey;
    @NotBlank private String model;
    private Double temperature;          // 可空
}
```

`src/main/java/com/lab/reservation/ai/vo/AiCredentialVO.java`:
```java
package com.lab.reservation.ai.vo;

import lombok.Data;

@Data
public class AiCredentialVO {
    private String provider;
    private String baseUrl;
    private String apiKeyMasked;   // sk-****末4位,永不返明文
    private String model;
    private Double temperature;
    private boolean configured;    // 是否已配(前端据此显空态)
}
```

- [ ] **Step 2: 写失败测试**

`src/test/java/com/lab/reservation/ai/service/AiCredentialServiceTest.java`:
```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.entity.UserAiCredential;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.UserAiCredentialMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AiCredentialServiceTest {

    @Mock UserAiCredentialMapper mapper;
    @Mock CryptoUtil crypto;
    @Mock LlmClient llmClient;          // test-call 真实走 LlmClient.testConnection
    @InjectMocks AiCredentialService service;

    @Test
    void saveStripsTrailingV1() {
        AiCredentialSaveDTO dto = new AiCredentialSaveDTO();
        dto.setProvider("deepseek");
        dto.setBaseUrl("https://api.deepseek.com/v1");
        dto.setApiKey("sk-1234567890");
        dto.setModel("deepseek-chat");
        dto.setTemperature(0.3);

        when(crypto.encrypt(any())).thenReturn("CIPHER");
        when(mapper.selectOne(any())).thenReturn(null);
        when(crypto.keyHash(any())).thenReturn("h");
        when(crypto.decrypt("CIPHER")).thenReturn("sk-1234567890");
        when(llmClient.testConnection(anyString(), anyString(), anyString())).thenReturn(true);

        service.save(1L, dto);

        org.mockito.ArgumentCaptor<UserAiCredential> cap =
                org.mockito.ArgumentCaptor.forClass(UserAiCredential.class);
        verify(mapper).insert(cap.capture());
        assertEquals("https://api.deepseek.com", cap.getValue().getBaseUrl());  // /v1 被 strip
    }

    @Test
    void saveRollsBackWhenTestFails() {
        AiCredentialSaveDTO dto = new AiCredentialSaveDTO();
        dto.setProvider("deepseek");
        dto.setBaseUrl("https://api.deepseek.com");
        dto.setApiKey("sk-bad");
        dto.setModel("deepseek-chat");
        when(mapper.selectOne(any())).thenReturn(null);
        when(llmClient.testConnection(anyString(), anyString(), anyString())).thenReturn(false);

        assertThrows(BusinessException.class, () -> service.save(1L, dto));
        verify(mapper, never()).insert(any());   // test 失败不落库
    }

    @Test
    void getMasksApiKey() {
        UserAiCredential row = new UserAiCredential();
        row.setProvider("deepseek");
        row.setBaseUrl("https://api.deepseek.com");
        row.setApiKeyCipher("CIPHER");
        row.setModel("deepseek-chat");
        row.setTemperature(0.3);
        when(mapper.selectOne(any())).thenReturn(row);
        when(crypto.decrypt("CIPHER")).thenReturn("sk-3b72afaa6d124c0cb33eceaf5ccc3756");

        AiCredentialVO vo = service.get(1L);
        assertTrue(vo.getApiKeyMasked().startsWith("sk-****"));
        assertTrue(vo.getApiKeyMasked().endsWith("3756"));
        assertFalse(vo.getApiKeyMasked().contains("3b72afaa"));
    }
}
```
(补 `import static org.mockito.ArgumentMatchers.anyString;`。)

- [ ] **Step 3: 跑测试验证失败**

Run: `mvn test -Dtest=AiCredentialServiceTest`
Expected: FAIL — `AiCredentialService` / `LlmClient` 不存在。

- [ ] **Step 4: 实现 LlmClient.testConnection(先建最小 LlmClient,Task 6 再完整化)**

⚠️ Task 3 依赖 `LlmClient.testConnection`,而 Task 6 才正式重命名。为避免循环依赖,**本步先创建 `LlmClient.java` 骨架含 `testConnection`**(Task 6 只补 `stream` + 熔断)。若已先做 Task 6 则跳过本步。

`src/main/java/com/lab/reservation/ai/service/LlmClient.java`(骨架):
```java
package com.lab.reservation.ai.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.model.openai.OpenAiChatModel;
import org.springframework.ai.model.openai.OpenAiChatOptions;
import org.springframework.ai.model.openai.api.OpenAiApi;
import org.springframework.stereotype.Service;

import java.time.Duration;

/** 临时建:仅 testConnection。stream + CircuitBreaker 在 Task 6 补。 */
@Slf4j
@Service
public class LlmClient {

    public boolean testConnection(String baseUrl, String apiKey, String model) {
        try {
            OpenAiApi api = OpenAiApi.builder().baseUrl(baseUrl).apiKey(apiKey).build();
            OpenAiChatOptions opt = OpenAiChatOptions.builder().model(model).build();
            OpenAiChatModel m = OpenAiChatModel.builder().openAiApi(api).defaultOptions(opt).build();
            String reply = ChatClient.create(m).prompt().user("hi").call().content();
            return reply != null && !reply.isBlank();
        } catch (Exception e) {
            log.warn("LLM testConnection failed for base={} model={}: {}", baseUrl, model, e.toString());
            return false;
        }
    }
}
```
⚠️ Spring AI 1.0.6 的 `OpenAiApi`/`OpenAiChatModel`/`OpenAiChatOptions` 的包名可能为 `org.springframework.ai.openai.*` 而非 `org.springframework.ai.model.openai.*`。**实施第一步先 grep 实际包名**:`grep -rn "class OpenAiChatModel" ~/.m2/repository/org/springframework/ai` 或 IDE 跳转确认,全文统一。

- [ ] **Step 5: 实现 AiCredentialService**

`src/main/java/com/lab/reservation/ai/service/AiCredentialService.java`:
```java
package com.lab.reservation.ai.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.UserAiCredential;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.UserAiCredentialMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class AiCredentialService {

    private final UserAiCredentialMapper mapper;
    private final CryptoUtil crypto;
    private final LlmClient llmClient;

    @Transactional
    public AiCredentialVO save(Long userId, AiCredentialSaveDTO dto) {
        String baseUrl = stripTrailingV1(dto.getBaseUrl().trim());

        // test-before-persist:失败不落库。抛 BusinessException(GlobalExceptionHandler 会保留
        // message 透传给前端;IllegalArgumentException 会被兜底吞成通用 BUSINESS_ERROR)。
        if (!llmClient.testConnection(baseUrl, dto.getApiKey(), dto.getModel())) {
            throw new BusinessException(ResultCode.BUSINESS_ERROR,
                    "连接测试失败:检查 base-url / api-key / model");
        }

        UserAiCredential row = mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
        boolean insert = (row == null);
        if (insert) {
            row = new UserAiCredential();
            row.setUserId(userId);
        }
        row.setProvider(dto.getProvider());
        row.setBaseUrl(baseUrl);
        row.setApiKeyCipher(crypto.encrypt(dto.getApiKey()));
        row.setModel(dto.getModel());
        row.setTemperature(dto.getTemperature());
        row.setValidated(1);
        if (insert) mapper.insert(row); else mapper.updateById(row);
        return toVo(row);
    }

    public AiCredentialVO get(Long userId) {
        UserAiCredential row = mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
        return row == null ? unconfigured() : toVo(row);
    }

    public void delete(Long userId) {
        mapper.delete(new QueryWrapper<UserAiCredential>().eq("user_id", userId));
    }

    /** 供 UserChatClientProvider 用:取明文 key。 */
    public String getPlainApiKey(Long userId) {
        UserAiCredential row = mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
        return row == null ? null : crypto.decrypt(row.getApiKeyCipher());
    }

    public UserAiCredential getRow(Long userId) {
        return mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
    }

    private AiCredentialVO toVo(UserAiCredential row) {
        AiCredentialVO vo = new AiCredentialVO();
        vo.setProvider(row.getProvider());
        vo.setBaseUrl(row.getBaseUrl());
        vo.setModel(row.getModel());
        vo.setTemperature(row.getTemperature());
        vo.setConfigured(true);
        String plain = crypto.decrypt(row.getApiKeyCipher());
        vo.setApiKeyMasked(mask(plain));
        return vo;
    }

    private AiCredentialVO unconfigured() {
        AiCredentialVO vo = new AiCredentialVO();
        vo.setConfigured(false);
        return vo;
    }

    /** sk-****末4位。短 key 兜底全 ****。 */
    static String mask(String plain) {
        if (plain == null || plain.length() < 4) return "****";
        return plain.substring(0, Math.min(3, plain.length())) + "****"
                + plain.substring(plain.length() - 4);
    }

    static String stripTrailingV1(String url) {
        return url.replaceAll("/+$", "").replaceAll("(?i)/v1$", "");
    }
}
```

- [ ] **Step 6: 跑测试验证通过**

Run: `mvn test -Dtest=AiCredentialServiceTest`
Expected: PASS。修测试里 `ArgumentCaptor…` 占位为真实验证 `verify(mapper).insert(arg.capture()); assertEquals("https://api.deepseek.com", arg.getValue().getBaseUrl());`。

- [ ] **Step 7: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/dto/AiCredentialSaveDTO.java src/main/java/com/lab/reservation/ai/vo/AiCredentialVO.java src/main/java/com/lab/reservation/ai/service/AiCredentialService.java src/main/java/com/lab/reservation/ai/service/LlmClient.java src/test/java/com/lab/reservation/ai/service/AiCredentialServiceTest.java
git commit -m "feat(ai): AiCredentialService — CRUD + test-before-persist + /v1 strip + mask"
```

---

## Task 4: UserChatClientProvider(per-user 缓存工厂)

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/service/UserChatClientProvider.java`
- Test: `src/test/java/com/lab/reservation/ai/service/UserChatClientProviderTest.java`

- [ ] **Step 1: 写失败测试**

`src/test/java/com/lab/reservation/ai/service/UserChatClientProviderTest.java`:
```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.entity.UserAiCredential;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.ai.chat.client.ChatClient;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class UserChatClientProviderTest {

    @Mock AiCredentialService credService;
    @Mock CryptoUtil crypto;
    @Mock ObjectProvider<ChatClient> defaultClientProvider;
    @Mock Environment env;

    @Test
    void noKeyInProdReturnsEmpty() {
        when(credService.getRow(1L)).thenReturn(null);
        when(env.acceptsProfiles(any())).thenReturn(false); // 非 dev
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        assertEquals(Optional.empty(), p.resolve(1L));
    }

    @Test
    void noKeyInDevFallsBackToDefaultClient() {
        ChatClient def = mock(ChatClient.class);
        when(credService.getRow(1L)).thenReturn(null);
        when(env.acceptsProfiles(any())).thenReturn(true);  // dev
        when(defaultClientProvider.getIfAvailable()).thenReturn(def);
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        Optional<ChatClient> cc = p.resolve(1L);
        assertTrue(cc.isPresent());
        assertSame(def, cc.get());
    }

    @Test
    void withKeyBuildsAndCaches() {
        UserAiCredential row = new UserAiCredential();
        row.setUserId(1L);
        row.setBaseUrl("https://api.deepseek.com");
        row.setApiKeyCipher("C");
        row.setModel("deepseek-chat");
        row.setTemperature(0.3);
        when(credService.getRow(1L)).thenReturn(row);
        when(crypto.decrypt("C")).thenReturn("sk-real");
        when(crypto.keyHash("sk-real")).thenReturn("h1");
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        Optional<ChatClient> a = p.resolve(1L);
        Optional<ChatClient> b = p.resolve(1L);   // 第二次走缓存
        assertTrue(a.isPresent());
        assertSame(a.get(), b.get());
        verify(credService, times(2)).getRow(1L);   // 注:缓存命中也查 row?——看实现
    }
}
```
(注:第三个测试的 `verify` 次数取决于缓存是否短 路 row 查询;若实现缓存命中即不查 row,改成 `times(1)`,与实现对齐。)

- [ ] **Step 2: 跑测试验证失败**

Run: `mvn test -Dtest=UserChatClientProviderTest`
Expected: FAIL — 类不存在。

- [ ] **Step 3: 实现 UserChatClientProvider**

`src/main/java/com/lab/reservation/ai/service/UserChatClientProvider.java`:
```java
package com.lab.reservation.ai.service;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.entity.UserAiCredential;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.model.openai.OpenAiChatModel;
import org.springframework.ai.model.openai.OpenAiChatOptions;
import org.springframework.ai.model.openai.api.OpenAiApi;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Optional;

/**
 * per-user ChatClient 缓存工厂。
 *
 * <p>resolve(userId):DB 有 key → decrypt + 按 (userId) 缓存,keyHash 变则重建;
 * 无 key + dev → 返回默认单例 ChatClient(yml 兜底);无 key + prod → empty。
 *
 * <p>cache:Caffeine,maxSize 256,expireAfterAccess 30m,防无界增长 + 陈旧。
 * save/delete 时调 {@link #evict(userId)} 主动失效。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserChatClientProvider {

    private final AiCredentialService credService;
    private final CryptoUtil crypto;
    private final ObjectProvider<ChatClient> defaultClientProvider;
    private final Environment env;

    private final Cache<Long, Entry> cache = Caffeine.newBuilder()
            .maximumSize(256)
            .expireAfterAccess(Duration.ofMinutes(30))
            .build();

    public Optional<ChatClient> resolve(Long userId) {
        // 1. 缓存命中且未变
        UserAiCredential row = credService.getRow(userId);
        if (row == null) {
            return devFallback();   // 无 key
        }
        String plain = crypto.decrypt(row.getApiKeyCipher());
        if (plain == null) {
            log.warn("user {} api_key decrypt failed, skipping", userId);
            return devFallback();
        }
        String hash = crypto.keyHash(plain);
        Entry cached = cache.getIfPresent(userId);
        if (cached != null && cached.keyHash.equals(hash)) {
            return Optional.of(cached.client);
        }
        // 2. 构建 / 重建
        ChatClient cc = build(row.getBaseUrl(), plain, row.getModel(), row.getTemperature());
        cache.put(userId, new Entry(cc, hash));
        return Optional.of(cc);
    }

    public void evict(Long userId) {
        cache.invalidate(userId);
    }

    private Optional<ChatClient> devFallback() {
        if (env.acceptsProfiles(Profiles.of("dev"))) {
            ChatClient def = defaultClientProvider.getIfAvailable();
            if (def != null) return Optional.of(def);
        }
        return Optional.empty();
    }

    private ChatClient build(String baseUrl, String apiKey, String model, Double temperature) {
        OpenAiApi api = OpenAiApi.builder().baseUrl(baseUrl).apiKey(apiKey).build();
        OpenAiChatOptions.Builder ob = OpenAiChatOptions.builder().model(model);
        if (temperature != null) ob.temperature(temperature);   // null → 模型默认,别塞 null
        OpenAiChatModel m = OpenAiChatModel.builder().openAiApi(api).defaultOptions(ob.build()).build();
        return ChatClient.create(m);
    }

    private record Entry(ChatClient client, String keyHash) {}
}
```
⚠️ 依赖 Caffeine:Spring Boot 已传递(`spring-boot-starter` 含 `com.github.benmanes.caffeine.cache`)。若解析失败,pom 加 `com.github.ben-manes.caffeine:caffeine`。
⚠️ 第三个测试 verify 次数:本实现每次 resolve 都查 row(为检测 key 变更),所以 `times(2)` 对。测试保留。

- [ ] **Step 4: 跑测试验证通过**

Run: `mvn test -Dtest=UserChatClientProviderTest`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/UserChatClientProvider.java src/test/java/com/lab/reservation/ai/service/UserChatClientProviderTest.java
git commit -m "feat(ai): UserChatClientProvider — per-user cached ChatClient + dev fallback"
```

---

## Task 5: AiCredentialController(REST)

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/controller/AiCredentialController.java`

- [ ] **Step 1: 实现控制器**

```java
package com.lab.reservation.ai.controller;

import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.service.AiCredentialService;
import com.lab.reservation.ai.service.UserChatClientProvider;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

/**
 * 用户 LLM 凭证(本人)。
 *
 * <p>注意:POST 故意不加 @Log —— 请求体含明文 apiKey,不能进 operation_log。
 * 无 @PreAuthorize:按 SecurityUserDetails 限定本人即可(人人可管自己的)。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Tag(name = "AI 凭证")
@RestController
@RequestMapping("/ai/credential")
@RequiredArgsConstructor
public class AiCredentialController {

    private final AiCredentialService credService;
    private final UserChatClientProvider provider;

    @Operation(summary = "查本人当前配置(key masked)")
    @GetMapping
    public Result<AiCredentialVO> get(@AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(credService.get(ud.getUserId()));
    }

    @Operation(summary = "保存/更新(test 失败不落库)")
    @PostMapping
    public Result<AiCredentialVO> save(@AuthenticationPrincipal SecurityUserDetails ud,
                                       @Valid @RequestBody AiCredentialSaveDTO dto) {
        AiCredentialVO vo = credService.save(ud.getUserId(), dto);
        provider.evict(ud.getUserId());   // key 变了,失效缓存
        return Result.ok(vo);
    }

    @Operation(summary = "删除(回到未配置)")
    @DeleteMapping
    public Result<?> delete(@AuthenticationPrincipal SecurityUserDetails ud) {
        credService.delete(ud.getUserId());
        provider.evict(ud.getUserId());
        return Result.ok();
    }
}
```
⚠️ test 失败时 `AiCredentialService.save` 抛 `BusinessException`(已定)。已验证
`GlobalExceptionHandler` 只对 `BusinessException` 保留 message 透传(`IllegalArgumentException`
会落到兜底 `Exception` handler 吞成通用 BUSINESS_ERROR + `printStackTrace`)。所以**必须**
用 `BusinessException` 而非 `IllegalArgumentException`,前端才能收到「连接测试失败:...」。

- [ ] **Step 2: 启动手测(需 Task 8 配置就绪后)**

本 task 单独无法完整手测(需前端 + 启动)。先编译过:`mvn compile`。手测放 Task 8 后。

- [ ] **Step 3: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/controller/AiCredentialController.java
git commit -m "feat(ai): AiCredentialController — GET/POST/DELETE own credential (no @Log)"
```

---

## Task 6: SiliconFlowClient → LlmClient(重命名 + stream 收 ChatClient)

**Files:**
- Rename: `SiliconFlowClient.java` → `LlmClient.java`
- Modify: `src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java`

- [ ] **Step 1: 重命名 + 改签名**

把 `SiliconFlowClient.java` 重命名 `LlmClient.java`(包不变)。若 Task 3 已建骨架,合并:保留 `testConnection`,把 `stream` 从 inject 单例改为收参数。

最终 `LlmClient.stream`:
```java
@CircuitBreaker(name = "llm", fallbackMethod = "streamFallback")
public Flux<String> stream(String systemPrompt,
                           List<Message> history,
                           ChatClient chatClient,                 // ← 新增参数
                           ToolCallback... toolCallbacks) {
    String reply = chatClient.prompt()
            .system(systemPrompt)
            .messages(history)
            .toolCallbacks(toolCallbacks)
            .call()
            .content();
    if (reply == null || reply.isEmpty()) return Flux.empty();
    java.util.List<String> chunks = new java.util.ArrayList<>();
    for (int i = 0; i < reply.length(); i += 12) {
        chunks.add(reply.substring(i, Math.min(i + 12, reply.length())));
    }
    return Flux.fromIterable(chunks);
}

@SuppressWarnings("unused")
public Flux<String> streamFallback(String systemPrompt,
                                   List<Message> history,
                                   ChatClient chatClient,
                                   ToolCallback[] toolCallbacks,
                                   Throwable t) {
    log.warn("LLM circuit breaker fallback: {}", t.getMessage());
    return Flux.error(new BusinessException(ResultCode.AI_UNAVAILABLE));
}
```
- 删 `LlmClient` 构造里的 `private final ChatClient chatClient;` 字段(不再 inject)。
- 删旧 `SiliconFlowClient.java` 文件。

- [ ] **Step 2: 改 AiAssistantServiceTest mock 签名**

`src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java`:
- 把 `SiliconFlowClient llm` 字段 → `LlmClient llm`(若用 @InjectMocks 按类型注入,改名即可)。
- mock stub:`when(llm.stream(anyString(), any(), any(ChatClient.class), any()))...` 或 `verify` 处加参数。
- 若 service 还未注入 provider(Task 7 做),本 task 测试可能编译失败 —— **与 Task 7 合并提交,或本 task 先 mock 一个 provider bean 返回 fixed client**。推荐:本 task + Task 7 连做。

- [ ] **Step 3: 编译验证**

Run: `mvn test-compile`
Expected: 通过(若 Task 7 未做,`AiAssistantService` 仍调 `siliconFlowClient.stream(prompt,history,toolCallbacks)` 三参版 → 编译失败 → 直接进 Task 7)。

- [ ] **Step 4: Commit(与 Task 7 合并)**

不单独 commit,合进 Task 7。

---

## Task 7: AiAssistantService 接 provider + AI_NOT_CONFIGURED 帧

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java`
- Modify: `src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java`

- [ ] **Step 1: 改 AiAssistantService**

字段加 `UserChatClientProvider provider`(由 `@RequiredArgsConstructor` 注入)。`siliconFlowClient` 字段重命名 `llmClient` 类型 `LlmClient`。

在 `handleUserMessage` 里,SecurityContext 注入之后、会话创建之前,插入 resolve:
```java
// per-user chat client(无 key → 提示去配置,prod 严格拒绝)
ChatClient userChatClient = provider.resolve(user.getUserId()).orElse(null);
if (userChatClient == null) {
    frameService.push(convIdIn, user, "error",
            Map.of("code", "AI_NOT_CONFIGURED",
                   "msg", "请先在 个人中心 → AI 助手配置 填写 API Key",
                   "action", "open_settings"));
    return;
}
```
⚠️ 注意:resolve 失败时 `convIdIn` 可能 null(新会话),frame 用 null convId 也能推(前端按 user queue 收)。或先把会话建出来再 push。推荐:把 resolve 放会话创建**之后**(`convId` 拿到后),这样 error 帧带正确 convId。重排顺序:
```
1. 限流
2. SecurityContext 注入
3. 会话创建/校验 → 拿 convId
4. provider.resolve → 失败 push error(convId) + return   ← 插这里
5. step_update / persist / for-loop
```

for-loop 里调改成传 userChatClient:
```java
llmClient.stream(
        promptBuilder.build(SystemPromptBuilder.extractRole(user), user.getUserId()),
        history,
        userChatClient,          // ← 传入
        toolCallbacks
).doOnNext(...)
```

- [ ] **Step 2: 改测试**

`AiAssistantServiceTest`:加一个 mock `UserChatClientProvider provider`,返回 `Optional.of(mock(ChatClient.class))`(走正常路径)+ 一个返回 `empty()` 验证 push 了 AI_NOT_CONFIGURED 帧。`llm` 字段改 `LlmClient`。

- [ ] **Step 3: 跑测试**

Run: `mvn test -Dtest=AiAssistantServiceTest`
Expected: PASS。

- [ ] **Step 4: Commit(Task 6+7 合并)**

```bash
git add -A src/main/java/com/lab/reservation/ai/service/LlmClient.java src/main/java/com/lab/reservation/ai/service/AiAssistantService.java src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java
git rm src/main/java/com/lab/reservation/ai/service/SiliconFlowClient.java
git commit -m "refactor(ai): SiliconFlowClient→LlmClient + per-user ChatClient resolve + AI_NOT_CONFIGURED"
```

---

## Task 8: 配置拆分 + auto-config exclude + resilience4j 迁移(零 key 启动)

**Files:**
- Modify: `src/main/resources/application.yml`
- Modify: `src/main/resources/application-siliconflow.yml`
- Modify: `src/main/resources/application-prod.yml`
- Modify: `src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java`

- [ ] **Step 1: 关键 spike —— 验证 Spring AI 1.0.6 缺 key 行为**

临时把 `application-siliconflow.yml` 里 `spring.ai.openai.api-key` 注释掉,跑 `mvn spring-boot:run -Dspring-boot.run.profiles=siliconflow,dev`:
- 若 boot **抛异常** → prod 必须 `spring.autoconfigure.exclude` 排除 chat auto-config。
- 若 boot **正常**(建空 bean / 懒加载)→ `@ConditionalOnBean` 够用,exclude 可选。

记录结论,据此决定 Step 4 是否加 exclude。还原 yml。

- [ ] **Step 2: 非密配置迁入 tracked application.yml**

`src/main/resources/application.yml` 末尾追加(从 siliconflow yml 搬来,全是非密):
```yaml
ai:
  assistant:
    ratelimit:
      capacity: 20
      refill-per-minute: 20
    context-window-turns: 10
    pending-timeout-minutes: 5
    rag:
      top-k: 5
      similarity-threshold: 0.6

spring:
  ai:
    vectorstore:
      chroma:
        client:
          host: http://localhost
          port: 9000
        collection-name: lab_manuals
        initialize-schema: true

# 熔断器(从 gitignored application-siliconflow.yml 迁来,实例改名 siliconflow→llm)
resilience4j:
  circuitbreaker:
    instances:
      llm:
        failure-rate-threshold: 50
        sliding-window-size: 10
        wait-duration-in-open-state: 60s
        permitted-number-of-calls-in-half-open-state: 3
```

- [ ] **Step 3: application-siliconflow.yml 只留密钥(gitignored)**

替换为(删掉 ai.assistant / chroma / resilience4j,只留 chat 兜底 + embedding 密钥):
```yaml
spring:
  ai:
    openai:
      # dev chat 兜底:profile=dev 且用户未配 BYO key 时用。
      # prod 不加载本文件(不激活 siliconflow profile)。
      base-url: https://api.deepseek.com
      api-key: ${DEEPSEEK_API_KEY:你本地的-deepseek-key}
      chat:
        options:
          model: deepseek-chat
          temperature: 0.3
          max-tokens: 4096
      # embedding(RAG)系统级 —— 本地 dev 用
      embedding:
        base-url: https://api.siliconflow.cn
        api-key: ${SILICONFLOW_API_KEY:你本地的-siliconflow-key}
        options:
          model: BAAI/bge-m3
          dimensions: 1024
```
⚠️ 把现有硬编码 key 改成 `${ENV:默认}` 形式,默认值填本地真 key(dev 方便)。**真 key 仍只在本 gitignored 文件**。

- [ ] **Step 4: application-prod.yml —— exclude + embedding env 占位**

追加(若 Step 1 结论需 exclude):
```yaml
spring:
  autoconfigure:
    exclude:
      # chat 纯 per-user(走 UserChatClientProvider 手搓 OpenAiChatModel),
      # 不依赖 auto-config;缺 key 时排除避免 boot 挂。embedding auto-config 独立保留。
      - org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration
  ai:
    openai:
      embedding:
        base-url: ${SPRING_AI_OPENAI_EMBEDDING_BASE_URL:}
        api-key: ${SPRING_AI_OPENAI_EMBEDDING_API_KEY:}
        options:
          model: ${SPRING_AI_OPENAI_EMBEDDING_OPTIONS_MODEL:BAAI/bge-m3}
```
⚠️ `OpenAiChatAutoConfiguration` 全限定名按 1.0.6 实际包名(Step 1 spike 时 grep 确认)。embedding env 缺 → RAG 关(下一步 conditional)。

- [ ] **Step 5: ChatClientConfig 条件化**

`src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java`:
```java
@Configuration
public class ChatClientConfig {

    /** dev 兜底用:仅当 Spring AI auto-config 建出 ChatClient.Builder 时才建默认 bean。
     *  prod(exclude chat auto-config)无此 bean,Provider 走 per-user 路径。 */
    @Bean
    @ConditionalOnBean(ChatClient.Builder.class)
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder.build();
    }
}
```
加 `import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;` + `import org.springframework.ai.chat.client.ChatClient;`。

- [ ] **Step 6: RAG 组件条件化(embedding 缺则关)**

依赖链 4 层(已核实):`RagManualTool`(@Component, `ai.tool`)→ 构造注入 `RagSearchService`
→ 构造注入 `VectorStore`(Chroma)→ 需 `EmbeddingModel`。**整链都要条件化**,否则 prod 无
embedding env 时 `RagManualTool` 仍尝试实例化缺失的 `RagSearchService` → boot
`UnsatisfiedDependencyException`。给以下 4 个类各加(按上游存在的 bean 条件):

```java
// RagSearchService
@ConditionalOnBean(org.springframework.ai.vectorstore.VectorStore.class)
// RagIngestService
@ConditionalOnBean(org.springframework.ai.vectorstore.VectorStore.class)
// RagManualTool  ← 别漏!(它是 @Component,不在 ai.service 包)
@ConditionalOnBean(RagSearchService.class)
```
Chroma `VectorStore` 本身由 Spring AI auto-config 建,embedding env 缺 → 该 auto-config 不建
`EmbeddingModel` → `VectorStore` bean 不存在 → 上面三个全跳过,链断得干净,boot 不挂。

⚠️ **不要**在 `ToolRegistry.availableFor` 里写「跳过 null 工具」—— `ToolRegistry.scan()` 用
`getBeansOfType`,bean 从未创建就不会被扫到,运行时根本没有 null 可跳。条件化放在 bean
定义侧(`@ConditionalOnBean`),不是注册侧。

- [ ] **Step 7: 启动验证(prod-like:零 chat key)**

```bash
# 模拟 prod:不激活 siliconflow profile,只给 master key + embedding env
AI_MASTER_KEY=$(openssl rand -base64 32) \
SPRING_AI_OPENAI_EMBEDDING_API_KEY=你embedding-key \
SPRING_AI_OPENAI_EMBEDDING_BASE_URL=https://api.siliconflow.cn \
mvn spring-boot:run -DskipTests -Dspring-boot.run.profiles=prod
```
Expected: boot 成功(无 chat key)。无 embedding env 时也应 boot 成功(RAG 关)。

- [ ] **Step 8: Commit**

```bash
git add src/main/resources/application.yml src/main/resources/application-prod.yml src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java
git commit -m "config(ai): zero-key boot — split yml, exclude chat auto-config, resilience4j llm, conditional RAG"
```
⚠️ **不要 `git add` `application-siliconflow.yml`** —— 它 gitignored + untracked(已核实),
`git add` 静默无效;若用 `git add -f` 会把真 key 泄进 git。Step 3 对它的编辑**只留在你本地
dev 机器**,不进 commit、不上服务器(服务器走 env,不需要这文件)。这正是设计意图。

---

## Task 9: 前端 types + api + store

**Files:**
- Create: `frontend/src/types/aiConfig.ts`
- Create: `frontend/src/api/aiCredential.ts`
- Create: `frontend/src/stores/aiConfig.ts`

- [ ] **Step 1: types**

`frontend/src/types/aiConfig.ts`:
```ts
export type AiProvider = 'deepseek' | 'openai' | 'siliconflow' | 'custom'

export interface AiCredentialVO {
  provider: string
  baseUrl: string
  apiKeyMasked: string
  model: string
  temperature: number | null
  configured: boolean
}

export interface AiCredentialSaveDTO {
  provider: AiProvider
  baseUrl: string
  apiKey: string
  model: string
  temperature?: number | null
}

export const PROVIDER_PRESETS: Record<AiProvider, { baseUrl: string; model: string }> = {
  deepseek:    { baseUrl: 'https://api.deepseek.com',   model: 'deepseek-chat' },
  openai:      { baseUrl: 'https://api.openai.com',     model: 'gpt-4o-mini' },
  siliconflow: { baseUrl: 'https://api.siliconflow.cn', model: 'deepseek-ai/DeepSeek-V3' },
  custom:      { baseUrl: '',                            model: '' },
}
```

- [ ] **Step 2: api**

`frontend/src/api/aiCredential.ts`(复用项目 axios `request`):
```ts
import { request } from './request'   // 按项目实际 axios 封装路径调整
import type { AiCredentialVO, AiCredentialSaveDTO } from '@/types/aiConfig'

export const getAiCredential = () =>
  request.get<AiCredentialVO>('/ai/credential')

export const saveAiCredential = (dto: AiCredentialSaveDTO) =>
  request.post<AiCredentialVO>('/ai/credential', dto)

export const deleteAiCredential = () =>
  request.delete('/ai/credential')
```
⚠️ 确认项目 `request` 实例导出路径(grep `frontend/src/api/request` 或 `./index`)。

- [ ] **Step 3: store**

`frontend/src/stores/aiConfig.ts`:
```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getAiCredential, saveAiCredential, deleteAiCredential } from '@/api/aiCredential'
import type { AiCredentialVO, AiCredentialSaveDTO } from '@/types/aiConfig'

export const useAiConfigStore = defineStore('aiConfig', () => {
  const credential = ref<AiCredentialVO | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  async function load() {
    loading.value = true
    try { credential.value = await getAiCredential() }
    finally { loading.value = false }
  }

  async function save(dto: AiCredentialSaveDTO) {
    saving.value = true
    try { credential.value = await saveAiCredential(dto) }
    finally { saving.value = false }
  }

  async function remove() {
    await deleteAiCredential()
    credential.value = null
  }

  return { credential, loading, saving, load, save, remove }
})
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && pnpm build`(或 `pnpm exec vue-tsc --noEmit`)
Expected: 无类型错。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/aiConfig.ts frontend/src/api/aiCredential.ts frontend/src/stores/aiConfig.ts
git commit -m "feat(fe): aiConfig types + api + store"
```

---

## Task 10: AiConfig.vue 设置页 + 个人中心 tab

**Files:**
- Create: `frontend/src/views/user/AiConfig.vue`
- Modify: 个人中心视图(定位:`grep -rl "个人中心\|UserProfile\|Profile" frontend/src/views/user/`)

- [ ] **Step 1: 定位个人中心入口**

Run: `grep -rl "个人中心" frontend/src/views frontend/src/router`
确认个人中心组件路径(如 `frontend/src/views/user/Profile.vue`)与 tab 机制(el-tabs)。

- [ ] **Step 2: 写 AiConfig.vue**

`frontend/src/views/user/AiConfig.vue`(深色风格遵循项目 `components/ui` token):
```vue
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAiConfigStore } from '@/stores/aiConfig'
import { PROVIDER_PRESETS, type AiProvider } from '@/types/aiConfig'

const store = useAiConfigStore()
const form = reactive({
  provider: 'deepseek' as AiProvider,
  baseUrl: PROVIDER_PRESETS.deepseek.baseUrl,
  apiKey: '',
  model: PROVIDER_PRESETS.deepseek.model,
  temperature: 0.3,
})

function onProviderChange(p: AiProvider) {
  const preset = PROVIDER_PRESETS[p]
  form.baseUrl = preset.baseUrl
  form.model = preset.model
}

async function onSave() {
  if (!form.apiKey) { ElMessage.warning('请填写 API Key'); return }
  await store.save({ ...form })
  ElMessage.success('已保存(连接测试通过)')
  form.apiKey = ''   // 不留明文在前端表单
}

async function onRemove() {
  await store.remove()
  ElMessage.success('已清除配置')
}

onMounted(() => store.load().then(() => {
  if (store.credential?.configured) {
    form.provider = store.credential.provider as AiProvider
    form.baseUrl = store.credential.baseUrl
    form.model = store.credential.model
    form.temperature = store.credential.temperature ?? 0.3
  }
}))
</script>

<template>
  <div class="ai-config">
    <el-form label-width="100px">
      <el-form-item label="服务商">
        <el-select v-model="form.provider" @change="onProviderChange">
          <el-option label="DeepSeek" value="deepseek" />
          <el-option label="OpenAI" value="openai" />
          <el-option label="硅基流动" value="siliconflow" />
          <el-option label="自定义" value="custom" />
        </el-select>
      </el-form-item>
      <el-form-item label="Base URL">
        <el-input v-model="form.baseUrl" placeholder="https://api.deepseek.com" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="form.apiKey" type="password" show-password
                  :placeholder="store.credential?.configured ? '已配置(重新填写则覆盖)' : 'sk-...'" />
      </el-form-item>
      <el-form-item label="模型">
        <el-input v-model="form.model" placeholder="deepseek-chat" />
      </el-form-item>
      <el-form-item label="温度">
        <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="store.saving" @click="onSave">保存(含连接测试)</el-button>
        <el-button v-if="store.credential?.configured" @click="onRemove">清除配置</el-button>
      </el-form-item>
    </el-form>
    <p class="ai-config__hint">
      你的 Key 仅加密存于本系统,不进服务器日志。chat 完全走你自己的额度。
    </p>
  </div>
</template>

<style scoped lang="scss">
.ai-config { max-width: 560px; }
.ai-config__hint { margin-top: 12px; font-size: 12px; color: var(--text-secondary); }
</style>
```

- [ ] **Step 3: 个人中心加 tab**

在个人中心组件里加一个 `el-tab-pane label="AI 助手配置"`,内容 `<AiConfig />`。import `AiConfig.vue`。

- [ ] **Step 4: 手测(需后端启动 Task 8)**

```bash
# 后端
mvn spring-boot:run -DskipTests -Dspring-boot.run.profiles=siliconflow,dev
# 前端
cd frontend && pnpm dev
```
浏览器登录 → 个人中心 → AI 助手配置 → 填 deepseek key + deepseek-chat → 保存 → 提示成功。
GET 回显 mask。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/user/AiConfig.vue <个人中心文件>
git commit -m "feat(fe): AiConfig settings page + profile tab"
```

---

## Task 11: AI_NOT_CONFIGURED 前端处理

**Files:**
- Modify: `frontend/src/types/ai.ts`(error 帧加 `action?`)
- Modify: `frontend/src/stores/ai.ts`(AI_NOT_CONFIGURED 分支)
- Modify: `frontend/src/components/ai/AiAssistant.vue`(去配置按钮)

- [ ] **Step 1: 类型加 action**

`frontend/src/types/ai.ts`:WsServerFrame error 加 `action?: string`。

- [ ] **Step 2: store 分支**

`frontend/src/stores/ai.ts` 的 `handleFrame` `case 'error'`:
```ts
case 'error':
  lastError.value = { code: frame.code, msg: frame.msg, action: frame.action }
  state.value = 'error'
  if (frame.code === 'AI_NOT_CONFIGURED') {
    // 标记需要跳配置,组件据此显按钮
    needsConfig.value = true
  }
  break
```
加 `const needsConfig = ref(false)`,return 里导出。`lastError` 类型加 `action?: string`。

- [ ] **Step 3: AiAssistant.vue 去配置按钮**

在错误展示区,当 `store.lastError?.code === 'AI_NOT_CONFIGURED'` 显按钮:
```vue
<el-button v-if="aiStore.lastError?.code === 'AI_NOT_CONFIGURED'"
           type="primary" size="small" @click="goConfig">
  去 AI 助手配置
</el-button>
```
```ts
function goConfig() {
  router.push('/user/profile')   // 个人中心路由,按实际
  aiStore.expanded = false
}
```

- [ ] **Step 4: 手测端到端**

prod-like 启动(零 chat key)+ 用户未配 key → 跟 AI 说话 → 收到「请先配置」+「去配置」按钮 → 点跳配置页 → 填 key 保存 → 回 AI 助手能正常对话。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/ai.ts frontend/src/stores/ai.ts frontend/src/components/ai/AiAssistant.vue
git commit -m "feat(fe): handle AI_NOT_CONFIGURED with go-config action"
```

---

## Task 12: 部署 env_file + .env 模板

**Files:**
- Modify: `docker-compose.prod.yml`
- Create: `.env.example`

- [ ] **Step 1: docker-compose.prod.yml 加 env_file**

`app` service 加:
```yaml
  app:
    env_file:
      - .env
    environment:
      SPRING_PROFILES_ACTIVE: prod
```
(保留原有 environment;`.env` 注入 `AI_MASTER_KEY` + 可选 embedding env。)

- [ ] **Step 2: .env.example(tracked 模板)**

```bash
# AI_MASTER_KEY:加密用户存 DB 的 key,必需。生成:openssl rand -base64 32
AI_MASTER_KEY=

# 可选 —— 要 RAG 检索手册才填(embedding 系统级)
SPRING_AI_OPENAI_EMBEDDING_API_KEY=
SPRING_AI_OPENAI_EMBEDDING_BASE_URL=https://api.siliconflow.cn
SPRING_AI_OPENAI_EMBEDDING_OPTIONS_MODEL=BAAI/bge-m3
```
确保 `.gitignore` 含 `.env`(不 ignore `.env.example`)。

- [ ] **Step 3: 生成真 master key(服务器上)**

服务器执行:`openssl rand -base64 32 > .env`(然后补 embedding 可选项)。**该 `.env` 不进 git**。

- [ ] **Step 4: 文档**

在 `DEPLOY-WITH-WEBHOOK.md` 末尾加「AI BYO-key 部署」节:说明 chat key 零进服务器、用户 UI 自配、`AI_MASTER_KEY` 必需、embedding 可选。

- [ ] **Step 5: Commit**

```bash
git add docker-compose.prod.yml .env.example DEPLOY-WITH-WEBHOOK.md
git commit -m "chore(deploy): env_file for AI_MASTER_KEY + embedding; .env.example template"
```

---

## 收尾验证

- [ ] `mvn test` 全绿
- [ ] `cd frontend && pnpm build` 无类型错
- [ ] prod-like 启动(零 chat key)boot 成功
- [ ] 用户配 key → AI 对话 + 工具调用正常
- [ ] 用户未配 key → AI_NOT_CONFIGURED + 去配置按钮
- [ ] `git log --oneline` 12 个 commit 干净;`git status` 无 key 残留
- [ ] grep 确认无真 key 进 tracked 文件:`git grep -nE "sk-[a-f0-9]{20,}"` 应只在 gitignored yml

---

## 风险 / 待验证(实施时盯)

1. **Spring AI 1.0.6 包名**:`OpenAiApi`/`OpenAiChatModel`/`OpenAiChatOptions`/`OpenAiChatAutoConfiguration` 的实际包(可能 `org.springframework.ai.openai.*` 非 `...model.openai.*`)。Task 3 Step 4 / Task 8 Step 1 grep 确认。
2. **缺 key boot 行为**:Task 8 Step 1 spike 定夺是否必须 exclude。
3. **Caffeine 依赖**:Spring Boot 已传递;若缺,pom 补。
4. **GlobalExceptionHandler 覆盖 IllegalArgumentException**:Task 5 Step 1 注释处;不覆盖则 save 改抛 BusinessException。
5. **RAG 组件条件化连锁**:`RagManualTool` 依赖 `RagSearchService`,embedding 缺时工具注册要兜底(Task 8 Step 6)。
