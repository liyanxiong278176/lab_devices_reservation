# 设计:每用户自带 LLM Key(BYO-key)+ 零 Key 启动

- 日期: 2026-07-09
- 状态: 已确认,待出实施计划
- 关联模块: `com.lab.reservation.ai.*`、`frontend/src/views/user/*`

## 1. 目标与动机

当前 AI 助手的 LLM 调用依赖启动时单例 `ChatClient` bean,密钥烧死在
`application-siliconflow.yml`(本地 gitignored)。问题:

1. **部署泄漏面**: 生产服务器要拿到 chat key 才能用,而 key 不能进 git。
2. **多租户**: 不同用户希望用各自平台的 key(各付各的账)。
3. **启动耦合**: yml 不上传 / env 缺 key 时,Spring AI auto-config 行为不确定,可能 boot 失败。

目标: **chat 完全 per-user,服务器零 chat key;应用「零 AI key 也能正常启动」**;
RAG(embedding)保留系统级、可选;本地 dev 工作流不破坏(继续用 yml 测)。

## 2. 已锁定决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| Chat 模式 | 每用户 BYO-key,严格 | 满足「服务器不存我 chat key」初衷 |
| 无用户 key 行为 | 严格拒绝(prod),提示去配置 | 服务器零 chat key |
| Embedding/RAG | 系统级(env),可选 | 共享只读向量库,维度/模型一致;无 key 自动关 |
| ChatModel 构造 | 缓存工厂(B 方案) | 连接池复用,失效干净 |
| 本地 dev chat | dev-only fallback 到 yml | 保住「本地用配置文件测」,prod 严格无 fallback |
| 启动 | 零 AI key 也能 boot | 只有 `AI_MASTER_KEY`(加密用)必需 |

## 3. 架构概览

```
┌─ 前端 ──────────────────────────────────────────────┐
│ 个人中心 →「AI 助手配置」tab                          │
│   provider 下拉 / base-url / api-key / model / temp  │
│   [测试连接] [保存]    Pinia store: aiConfig          │
└──────────────────────────────────────────────────────┘
              │ REST (/ai/credential)
              ▼
┌─ 后端 ai 模块 ───────────────────────────────────────┐
│ AiCredentialController   GET/POST/DELETE 本人凭证     │
│        │ 保存前 AiCredentialService.test() 真连一次   │
│        ▼                                              │
│ UserAiCredential (entity) ← Flyway V7, api_key 加密  │
│        │ CryptoUtil (AES-GCM, master key from env)    │
│        ▼                                              │
│ UserChatClientProvider.resolve(userId)               │
│   ├ 有 DB key → decrypt → build/cache ChatClient      │
│   ├ 无 key + dev → 返回默认单例 ChatClient(yml 兜底) │
│   └ 无 key + prod → Optional.empty()                  │
│        ▼                                              │
│ AiAssistantService.handleUserMessage                  │
│   resolve 失败 → push AI_NOT_CONFIGURED 帧(带跳转)   │
│   成功 → LlmClient.stream(prompt, history, cc, tools) │
│        │ @CircuitBreaker("llm")                       │
│        ▼  Embedding 走系统级 auto-config(@Conditional)│
│        OpenAiEmbeddingModel + Chroma VectorStore       │
│        (无 env embedding key → 整块不建,RAG 关)      │
└──────────────────────────────────────────────────────┘
```

## 4. 数据模型

Flyway 新增 `src/main/resources/db/migration/V7__user_ai_credential.sql`:

```sql
CREATE TABLE IF NOT EXISTS user_ai_credential (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  user_id         BIGINT       NOT NULL,
  provider        VARCHAR(32)  NOT NULL,        -- deepseek/openai/siliconflow/custom
  base_url        VARCHAR(255) NOT NULL,
  api_key_cipher  TEXT         NOT NULL,        -- AES-GCM 密文,IV 前置;明文永不落库
  model           VARCHAR(64)  NOT NULL,
  temperature     DOUBLE       NULL,            -- 可空,默认 0.3
  validated       TINYINT      NOT NULL DEFAULT 0,
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- `user_id` 唯一:一用户一套 chat 配置。
- 只加密 `api_key`;provider / base_url / model / temperature 明文(非密)。
- 老环境直接跳过(`baseline-on-migrate` + `IF NOT EXISTS`)。

实体 `UserAiCredential` + Mapper `UserAiCredentialMapper`。

## 5. 组件

### 5.1 CryptoUtil

- AES-GCM(256),每次加密随机 12B IV,前置密文。
- master key 来自 env `AI_MASTER_KEY`(32B base64)。
- dev 缺失 `AI_MASTER_KEY` → 从固定 dev 派生值 + 启动 WARN(仅 dev profile 允许)。
- 提供 `encrypt(plain)` / `decrypt(cipher)`。
- master key 轮换(全表 re-encrypt)列为后续任务,本期不做。

### 5.2 UserChatClientProvider(核心)

```java
resolve(userId) -> Optional<ChatClient>
  1. 查 user_ai_credential by userId
  2. 命中:
     - decrypt api_key
     - cache key = userId;entry = {ChatClient, keyHash(明文 key 的 hash)}
     - 命中且 keyHash 一致 → 返回缓存
     - 否则 build:
         OpenAiApi api = OpenAiApi.builder().baseUrl(url).apiKey(key).build();
         OpenAiChatOptions.Builder ob = OpenAiChatOptions.builder().model(model);
         if (temp != null) ob.temperature(temp);   // null → 不设,用模型默认(别把 null 塞进 builder)
         OpenAiChatOptions opt = ob.build();
         OpenAiChatModel m = OpenAiChatModel.builder().openAiApi(api).defaultOptions(opt).build();
         ChatClient cc = ChatClient.create(m);
       存 cache,返回
  3. 未命中:
     - profile=dev 且默认 ChatClient bean 存在 → 返回默认(yml 兜底)
     - 否则(prod,或 dev 无默认)→ Optional.empty()
  save(userId) / delete(userId):主动 evict 该 userId 缓存
```

- cache:Caffeine,`maximumSize(256)` + `expireAfterAccess(30m)`,防无界增长 + 陈旧。
- 线程安全:`computeIfAbsent` 重建。
- 默认 ChatClient bean(`ChatClientConfig`)改 `@ConditionalOnBean(ChatClient.Builder)`,prod 无 yml key 时不建 → Provider 用 `ObjectProvider<ChatClient>` 注入,缺失即 null。

### 5.3 LlmClient(由 SiliconFlowClient 重命名)

- 签名:`stream(systemPrompt, history, chatClient, toolCallbacks)` —— 多收一个
  `ChatClient` 参数,不再 inject 单例。
- `@CircuitBreaker(name = "llm", fallbackMethod = "streamFallback")`(由 `siliconflow` 改名)。
- 熔断器全局单一(per-user 熔断器过度,thesis 不做)。
- 流式模拟逻辑(.call() + 12 字 chunk)保持不变。

### 5.4 AiCredentialController + Service

REST(`/ai/credential`,全部按 `SecurityUserDetails.getUserId()` 限定本人):

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/ai/credential` | 返回当前配置,`api_key` 永远 mask(`sk-****末4位`),不返明文 |
| POST | `/ai/credential` | test call → ok 才 encrypt+persist+evict cache |
| DELETE | `/ai/credential` | 删 + evict |

- `POST` 入参 DTO:`{provider, baseUrl, apiKey, model, temperature}`。
- **base-url 规范化**:保存前 strip 尾部 `/v1`(参考 commit `d83c5a1` —— Spring AI
  自动拼 `/v1`,用户若带会双拼成 `/v1/v1` 报 404)。静默纠正比抛 404 友好。
- test call:用提交 key 临时 build ChatClient,`.user("hi").call()`,超时 10s;
  失败返回原因(key 无效 / model 不存在 / base-url 错)且**不落库**。
- `validated` 字段:test-before-persist 决定了它实际恒为 1(失败就不存)。
  保留作状态留痕,**别**为它过度设计「编辑时 re-validate」流程。

### 5.5 AiAssistantService.handleUserMessage 改动

入口加(per-user 解析):

```java
ChatClient cc = provider.resolve(user.getUserId()).orElse(null);
if (cc == null) {
    frameService.push(convId, user, "error",
        Map.of("code","AI_NOT_CONFIGURED",
               "msg","请先在 个人中心 → AI 助手配置 填写 API Key",
               "action","open_settings"));
    return;
}
// 原 siliconFlowClient.stream(prompt, history, toolCallbacks)
// → llmClient.stream(prompt, history, cc, toolCallbacks)
```

finally 清理不变。SecurityContext 注入逻辑不变。

### 5.6 前端

- 个人中心新 tab `frontend/src/views/user/AiConfig.vue`:
  - provider 下拉(预设自动填 base-url + model):
    - DeepSeek → `https://api.deepseek.com` + `deepseek-chat`
    - OpenAI → `https://api.openai.com` + `gpt-4o-mini`
    - SiliconFlow → `https://api.siliconflow.cn` + `deepseek-ai/DeepSeek-V3`
    - 自定义 → 留空手填
  - 表单:base-url、api-key(password)、model、temperature(slider 0–1)。
  - `[测试连接]` 调 POST 带 dry-run / 或直接保存触发 test。
  - `[保存]` 成功提示 + mask 回显。
- 新 Pinia store `frontend/src/stores/aiConfig.ts`:load / save / test。
- AI 助手(`AiAssistant.vue` / `stores/ai.ts`)收到 `AI_NOT_CONFIGURED` 帧 →
  显示「去配置」按钮,点击展开个人中心 AI 配置 tab。

## 6. 配置拆分(零 Key 启动的关键)

`application-siliconflow.yml`(本地 gitignored,**仅 dev**)重构后只剩密钥:

```yaml
spring:
  ai:
    openai:
      api-key: ${DEEPSEEK_KEY}          # dev chat 兜底用(prod 不读)
      chat:
        options: { model: deepseek-chat, temperature: 0.3 }
      embedding:
        base-url: https://api.siliconflow.cn
        api-key: ${SILICONFLOW_KEY}
        options: { model: BAAI/bge-m3, dimensions: 1024 }
```

非密调优搬进 **tracked** `application.yml` / `application-prod.yml`:

```yaml
ai:
  assistant:
    ratelimit: { capacity: 20, refill-per-minute: 20 }
    context-window-turns: 10
    pending-timeout-minutes: 5
    rag: { top-k: 5, similarity-threshold: 0.6 }
spring:
  ai:
    vectorstore:
      chroma:
        client: { host: http://localhost, port: 9000 }   # prod 用 docker 网络
        collection-name: lab_manuals
        initialize-schema: true
```

### 启动 auto-config 改造

- **chat 默认 bean + auto-config(load-bearing)**:`ChatClientConfig` 加
  `@ConditionalOnBean(ChatClient.Builder)` 只挡**下游** ChatClient bean,挡不住
  auto-config 本身。**零 key 启动的成败**取决于 Spring AI 1.0.6 的
  `OpenAiChatAutoConfiguration` 在 `spring.ai.openai.api-key` 缺失时是「建无效 bean」
  还是「boot 抛异常」。实施第一步必须验证:
  - 若缺 key 会抛异常 → prod 必须排除该 auto-config:
    `spring.autoconfigure.exclude: org.springframework.ai.model.openai.autoconfigure.OpenAiChatAutoConfiguration`
    (chat 纯 per-user,走 `OpenAiApi.builder()`/`OpenAiChatModel.builder()`/`ChatClient.create()`,
    根本不依赖这个 auto-config)。
  - `OpenAiEmbeddingAutoConfiguration` 是**独立** auto-config,可保持启用(RAG 用)。
  - dev 不排除(需默认 bean 做兜底)。
- **embedding 可选**:VectorStore / RAG 组件加 `@ConditionalOnBean(EmbeddingModel)`
  或 `@ConditionalOnProperty("spring.ai.openai.embedding.api-key")`;
  env 无 embedding key → bean 不建 → RAG 关,chat 不受影响。
- **resilience4j 实例改名 + 迁移**:`SiliconFlowClient→LlmClient` 把 `@CircuitBreaker(name)`
  从 `siliconflow` 改 `llm`。resilience4j 配置 `resilience4j.circuitbreaker.instances.siliconflow`
  当前在 gitignored `application-siliconflow.yml` —— 必须改名 `instances.llm` 并挪进
  **tracked** `application.yml`(非密),否则 Resilience4j boot 时 fail-fast 报实例不存在。
  ⚠️ spec 文件清单/section 6 tracked 块此前漏了这块,别丢。

### 服务器最终 env(gitignored `.env`,`docker-compose.prod.yml` 用 `env_file` 引)

```
AI_MASTER_KEY=<32B base64>                                  # 必需,加密 DB 内用户 key
SPRING_AI_OPENAI_EMBEDDING_API_KEY=<siliconflow key>        # 可选,要 RAG 才填
SPRING_AI_OPENAI_EMBEDDING_BASE_URL=https://api.siliconflow.cn
SPRING_AI_OPENAI_EMBEDDING_OPTIONS_MODEL=BAAI/bge-m3
```

chat key 零进服务器。compose 文件 tracked 但不含密钥(只 `env_file: .env`)。

## 7. 安全

- DB 只存 `api_key_cipher`(AES-GCM);明文不落库、不出现在日志、不进 GET 响应。
- master key 走 env,不进 git。
- key 解密后驻留 cache(ChatClient 持有),内存 dump 理论可取 —— thesis 可接受;
  生产级需 vault / KMS(列后续)。
- GET 永远 mask(`sk-****末4位`)。
- 一切凭证 CRUD 按 `SecurityUserDetails.getUserId()` 限定本人,无越权。
- **审计日志脱敏(关键)**:`OperationLogAspect` 会序列化 controller 方法入参/返回。
  `POST /ai/credential` 的请求体含**明文 apiKey** → 不能写进 `operation_log` 表。
  处置:该端点不加 `@Log`,或入参 DTO 的 `apiKey` 字段用自定义序列化器 redact。
  `GET` 返回已 mask,无此问题。
- **在途流不被影响**:用户改 key 时 evict 只影响后续 resolve;在途 ChatClient 用旧 key 跑完,
  属可接受。
- 模型名 `deepseek-v4-flash` 存疑(官方为 `deepseek-chat`/`deepseek-reasoner`);
  test-connection 会兜住,失败即提示换名。
- **dev 运行命令不变**:`-Dspring-boot.run.profiles=siliconflow,dev` 仍要带 `siliconflow`
  才会加载 `application-siliconflow.yml`(dev chat 兜底 + embedding 都靠它)。

## 8. 测试

- **单元**:
  - `CryptoUtil` 加解密往返、不同 IV、空串。
  - `UserChatClientProvider` cache hit / miss / keyHash 变更失效 / save/delete evict;
    dev fallback 返回默认 bean;prod 无 key 返回 empty(用 `@Profile`/mock Environment)。
  - `AiCredentialController` CRUD + mask + test 失败不落库(mock mapper + provider)。
- **slice / 集成**:留真实 key 手测(thesis 防御演示):配错 key 看 AI_NOT_CONFIGURED;
  配对 key 看正常对话 + 工具调用。
- 现有 `AiAssistantServiceTest` mock 签名更新(`LlmClient.stream` 多一参)。

## 9. 不做(Out of Scope)

- master key 轮换 / 全表 re-encrypt(后续)。
- per-user 熔断器 / 配额(后续)。
- embedding per-user(已否决,一致性风险)。
- vault / KMS 托管 master key(生产级硬化,后续)。
- 真流式(当前 .call() + chunk 模拟,不动)。

## 10. 变更文件清单(预估)

后端:
- 新:`V7__user_ai_credential.sql`、`UserAiCredential`、`UserAiCredentialMapper`、
  `CryptoUtil`、`UserChatClientProvider`、`AiCredentialController`、`AiCredentialService`、
  dto/vo 若干。
- 改:`AiAssistantService`(resolve + error frame)、`SiliconFlowClient→LlmClient`、
  `ChatClientConfig`(条件化)、`application*.yml` 拆分(含 resilience4j `instances.llm`
  从 gitignored yml 迁 tracked `application.yml`)、`AiAssistantServiceTest`。

前端:
- 新:`views/user/AiConfig.vue`、`stores/aiConfig.ts`、`api/aiCredential.ts`、
  `types/aiConfig.ts`。
- 改:个人中心路由加 tab、`stores/ai.ts`(AI_NOT_CONFIGURED 分支)、`AiAssistant.vue`(去配置按钮)。

部署:
- 改:`docker-compose.prod.yml`(`env_file: .env`)、新增服务器 `.env` 模板说明。
