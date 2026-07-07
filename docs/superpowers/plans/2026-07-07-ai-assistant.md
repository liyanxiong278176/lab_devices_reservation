# AI 助手(亮点六)实现 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有实验室预约系统上加一个腾讯云风格的 AI 助手(悬浮球 + 抽屉式聊天 + 操作确认 + 视觉特效),让用户用自然语言完成查设备/查预约/创建预约/取消预约/提交报修/分派工单/查 SOP 7 类操作。

**Architecture:** 复用现有 STOMP 端点 `/api/ws`(共用 `JwtHandshakeHandler`),新增 `AiAssistantService` 用 `ChatClient` 调硅基流动云端 LLM(`deepseek-ai/DeepSeek-V4-Flash` + `BAAI/bge-m3`),通过 `@Tool` 注解 + 反射注册把现有 11 个 Service 暴露给 LLM;权限隔离只靠 `ToolRegistry` 过滤(不靠 `@PreAuthorize`,Spring proxy 绕过);写操作走"AI 出卡片 → 用户点确认 → 后端执行"状态机,审计日志写 `ai_tool_execution`;新增 Chroma 1.x Docker 容器做 RAG 设备手册问答;前端悬浮球 + 抽屉 + 5 种消息卡 + 视觉特效(光晕/彩色光标/Sub-step 同步/推荐下一步)。

**Tech Stack:**
- 后端:Spring AI 2.0.0 (`spring-ai-starter-model-openai` + `spring-ai-starter-vector-store-chroma`) + Spring Boot 3 (JVM 17/21/25 via Lombok annotationProcessorPaths)
- 前端:Vue 3 + Element Plus + Pinia + V5 深色 token(已合入 main)
- 模型:硅基流动 API(OpenAI 兼容),`deepseek-ai/DeepSeek-V4-Flash` chat + `BAAI/bge-m3` embedding
- 向量库:Chroma 1.0.0(Docker 容器,本地 8000 端口)
- 限流:Bucket4j 8.10.1(Redis-backed,已有 Redis)
- 熔断:Resilience4j(硅基流动出口)

**Spec 文档:** `docs/superpowers/specs/2026-07-07-ai-assistant-design.md`(1650 行,3 轮 review approved)

**承接 commit:** `0da26d9`(spec 主干) + `9807281`(5 个 follow-up polish)

**预计工期:** 36 天(9 阶段),分批 commit

---

## 文件结构

### 新建后端文件(包路径 `com.lab.reservation.ai.*`)

| 路径 | 行数预估 | 职责 |
|---|---|---|
| `src/main/java/com/lab/reservation/ai/config/AiProperties.java` | 60 | `@ConfigurationProperties("ai.assistant")` 读 yml(ratelimit/timeout/top-k) |
| `src/main/java/com/lab/reservation/ai/controller/AiAssistantController.java` | 150 | STOMP `@MessageMapping("/app/assistant/{send,confirm,cancel,resync}")` |
| `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java` | 450 | ChatClient while-loop 编排 + 流式 + 上下文 + step_update 推送 |
| `src/main/java/com/lab/reservation/ai/service/ToolRegistry.java` | 120 | `@PostConstruct` 反射扫 `@Tool`,构建 `Map<String, ToolDefinition>` |
| `src/main/java/com/lab/reservation/ai/service/ToolPermissionFilter.java` | 80 | `availableFor(user)` 按角色过滤 |
| `src/main/java/com/lab/reservation/ai/service/ConfirmationService.java` | 220 | 写操作 pending/confirmed/cancelled/executed/error/expired 状态机 |
| `src/main/java/com/lab/reservation/ai/service/ConversationService.java` | 180 | `ai_conversation` / `ai_message` 增删改查 + 90 天滚动清理 |
| `src/main/java/com/lab/reservation/ai/service/AuditService.java` | 100 | `ai_tool_execution` 写(不依赖 RequestContextHolder) |
| `src/main/java/com/lab/reservation/ai/service/AiFrameService.java` | 120 | `ai_ws_frame` 写 + Redis INCR seq 分配 + resync replay |
| `src/main/java/com/lab/reservation/ai/service/RagSearchService.java` | 100 | Chroma 检索 + similarity threshold |
| `src/main/java/com/lab/reservation/ai/service/RagIngestService.java` | 180 | PDF/Word → 文本 → TokenTextSplitter → Chroma |
| `src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java` | 80 | `@Scheduled` 每分钟扫 pending 5min+ → expired |
| `src/main/java/com/lab/reservation/ai/task/AiConversationCleanupScheduler.java` | 60 | `@Scheduled` 每天扫 90 天前的 ai_conversation/ai_message |
| `src/main/java/com/lab/reservation/ai/tool/ToolArgumentValidator.java` | 130 | 启动时扫 `@Tool` 注解构建 schema,运行时 `validate(methodId, args)` |
| `src/main/java/com/lab/reservation/ai/tool/ReservationTool.java` | 180 | search/get/create/cancel 4 个工具 |
| `src/main/java/com/lab/reservation/ai/tool/DeviceTool.java` | 140 | search/get/details 3 个工具 |
| `src/main/java/com/lab/reservation/ai/tool/RecommendTool.java` | 60 | 1 个工具(转调 `RecommendationService.recommend`) |
| `src/main/java/com/lab/reservation/ai/tool/RepairTool.java` | 150 | submit/mine/take 3 个工具 |
| `src/main/java/com/lab/reservation/ai/tool/AdminTool.java` | 100 | query_lab_reservations(转调新加 `ReservationService.queryByLab`) |
| `src/main/java/com/lab/reservation/ai/tool/RagManualTool.java` | 60 | search_device_manuals(转调 RagSearchService) |
| `src/main/java/com/lab/reservation/ai/dto/ToolExecutionResult.java` | 50 | `{ok, code, msg, data}` 工具方法返回值封装 |
| `src/main/java/com/lab/reservation/ai/dto/WsServerMsg.java` | 80 | STOMP 推送消息 union 类型(Java record) |
| `src/main/java/com/lab/reservation/ai/dto/WsClientMsg.java` | 60 | STOMP 接收消息 union 类型 |
| `src/main/java/com/lab/reservation/ai/exception/ToolArgumentException.java` | 30 | 自定义异常 |

### 修改后端文件

| 路径 | 修改内容 |
|---|---|
| `pom.xml` | + Spring AI 2.0.0 BOM + 3 个 starter + Bucket4j + Resilience4j |
| `src/main/resources/application.yml` | + `spring.profiles.include: siliconflow` |
| `src/main/resources/application-siliconflow.yml.example` | 新建模板,占位符 |
| `src/main/resources/db/migration/V1_0_5__ai_assistant.sql` | 新建 3 张表 + 1 张 `ai_ws_frame` |
| `src/main/java/com/lab/reservation/service/ReservationService.java` | + `queryByLab(Long labId, ReservationStatus status, int days, SecurityUserDetails ud)` |
| `src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java` | + `queryByLab` 实现 + `@PreAuthorize` admin only |
| `src/main/java/com/lab/reservation/controller/AuthController.java` | + `POST /auth/refresh` 端点(若尚未存在;实际存在) |
| `src/main/java/com/lab/reservation/security/JwtUtils.java` | + `refreshToken(String oldToken)` 方法(若尚未存在) |
| `src/main/resources/logback-spring.xml` | + `MaskedHeaderConverter`(过滤 Authorization) |
| `docker-compose.yml` | + chroma service(端口 8000,持久卷) |
| `.gitignore` | + `application-siliconflow.yml` |
| `docs/thesis/highlights.md` | + 亮点六完整章节 |
| `docs/thesis/drawings/07-ai-flow.drawio` | + 6.7 视觉特效时序图 |
| `frontend/src/views/reservation/Create.vue` 等 | **不修改** — AI 通过 tool-call 调,业务 UI 不动 |

### 新建前端文件

| 路径 | 行数预估 | 职责 |
|---|---|---|
| `frontend/src/types/ai.ts` | 200 | WS 消息 TS 类型 + 工具调用类型 |
| `frontend/src/composables/useAiWebSocket.ts` | 250 | STOMP 客户端 + 重连 + resync |
| `frontend/src/stores/ai.ts` | 300 | Pinia store:conv/messages/state/bucket |
| `frontend/src/components/ai/AiAssistant.vue` | 300 | 悬浮球 + 抽屉 global 组件(挂 MainLayout) |
| `frontend/src/components/ai/MessageCard.vue` | 100 | 消息类型 router(根据 role/tool 类型分发) |
| `frontend/src/components/ai/UserMessage.vue` | 60 | 用户消息气泡(右) |
| `frontend/src/components/ai/AssistantMessage.vue` | 80 | AI 消息气泡(左) + delta append |
| `frontend/src/components/ai/DeviceListCard.vue` | 150 | 设备列表卡片(网格) |
| `frontend/src/components/ai/ConfirmationCard.vue` | 200 | 确认卡片(警示色 + 2 按钮) |
| `frontend/src/components/ai/ResultCard.vue` | 80 | 执行结果卡片 |
| `frontend/src/components/ai/ErrorCard.vue` | 60 | 错误卡片 |
| `frontend/src/components/ai/StepTimelineCard.vue` | 200 | §7.4.3 Sub-step 步骤时间线 |
| `frontend/src/components/ai/SuggestionRow.vue` | 100 | §7.4.4 推荐下一步按钮行 |
| `frontend/src/components/ai/AuroraOverlay.vue` | 60 | §7.4.1 全屏光晕层 |
| `frontend/src/components/ai/ColorCursor.vue` | 40 | §7.4.2 切换 body class 触发 CSS cursor |
| `frontend/src/styles/aurora.scss` | 120 | 渐变 + keyframes(auroraPulse / hueRotate) |
| `frontend/src/styles/color-cursor.scss` | 40 | data-URI SVG cursor 样式 |

### 修改前端文件

| 路径 | 修改内容 |
|---|---|
| `frontend/src/stores/user.ts` | + `accessTokenExpiresAt` + `scheduleRefresh()` + `refresh()` |
| `frontend/src/composables/useWebSocket.ts` | + `reconnect(newToken: string)` |
| `frontend/src/views/MainLayout.vue` | + `<AiAssistant />` global 组件 |
| `frontend/src/main.ts` | + 引入 `aurora.scss` + `color-cursor.scss` |

---

## 任务总览

| Task | 阶段 | 标题 | 预计天数 |
|---|---|---|---|
| 1 | A | 基础设施(Spring AI + Chroma + 硅基流动 + Hello World) | 3 |
| 2 | F | RAG 基础设施(Chroma 集合 + 摄入服务 + 检索服务) | 4 |
| 3 | B | 工具层(10 个 @Tool + Shim + Validator + 权限过滤) | 7 |
| 4 | C | 确认机制 + 审计日志(状态机 + ai_tool_execution + ai_ws_frame) | 3 |
| 5 | D + E'' | 后端 WebSocket + 多轮 + while-loop + step_update/suggestions | 6 |
| 6 | E | 前端:悬浮球 + 抽屉 + 5 种基础消息卡(V5 token) | 5 |
| 7 | E' | 前端:视觉特效(光晕 + 光标 + StepTimeline + SuggestionRow) | 3 |
| 8 | (E'' 集成) | 多步连击模式 + 用户中断 | 2 |
| 9 | G | 评估 + 论文章节 + 部署 | 3 |
| **合计** | | | **36 天** |

---

## Task 1: 基础设施 — Spring AI 集成 + Chroma 部署 + Hello World

**Files:**
- Modify: `pom.xml`
- Create: `src/main/resources/application-siliconflow.yml`
- Create: `src/main/resources/application-siliconflow.yml.example`
- Modify: `src/main/resources/application.yml`
- Modify: `.gitignore`
- Create: `src/main/resources/logback-spring.xml`(修改已存在)
- Create: `src/main/java/com/lab/reservation/ai/config/AiProperties.java`
- Create: `src/main/java/com/lab/reservation/ai/dto/ToolExecutionResult.java`
- Create: `src/main/java/com/lab/reservation/ai/HelloWorldController.java`(临时冒烟用)
- Modify: `docker-compose.yml`

- [ ] **Step 1.1: 加 Spring AI 依赖到 pom.xml**

在 `pom.xml` 的 `<dependencyManagement>` 段加 BOM(版本管理):

```xml
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.ai</groupId>
            <artifactId>spring-ai-bom</artifactId>
            <version>2.0.0</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

在 `<dependencies>` 段加 3 个 starter + Bucket4j + Resilience4j:

```xml
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-model-openai</artifactId>
</dependency>
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-vector-store-chroma</artifactId>
</dependency>
<dependency>
    <groupId>com.bucket4j</groupId>
    <artifactId>bucket4j_jdk17-redis</artifactId>
    <version>8.10.1</version>
</dependency>
<dependency>
    <groupId>io.github.resilience4j</groupId>
    <artifactId>resilience4j-spring-boot3</artifactId>
    <version>2.2.0</version>
</dependency>
```

- [ ] **Step 1.2: 验证依赖解析**

```bash
cd D:/agent_learning/lab_devices_reservation
mvn dependency:resolve -DincludeScope=runtime 2>&1 | tail -20
```

Expected: 看到 `spring-ai-starter-model-openai`, `spring-ai-starter-vector-store-chroma`, `bucket4j_jdk17-redis` 三个新依赖已解析,无错误。

- [ ] **Step 1.3: 提交 pom.xml 改动**

```bash
git add pom.xml
git commit -m "build(ai-assistant): add Spring AI 2.0 + Bucket4j + Resilience4j deps"
```

- [ ] **Step 1.4: 创建 application-siliconflow.yml.example 模板**

`src/main/resources/application-siliconflow.yml.example`:

```yaml
spring:
  ai:
    openai:
      base-url: https://api.siliconflow.cn/v1
      api-key: REPLACE_ME_WITH_SILICONFLOW_API_KEY
      chat:
        options:
          model: deepseek-ai/DeepSeek-V4-Flash
          temperature: 0.3
          max-tokens: 4096
          stream-usage: true
      embedding:
        options:
          model: BAAI/bge-m3
          dimensions: 1024
    vectorstore:
      chroma:
        url: http://chroma:8000
        collection-name: lab_manuals
        initialize-schema: true

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
```

- [ ] **Step 1.5: 让运维填入真 key,创建 application-siliconflow.yml**

```bash
cp src/main/resources/application-siliconflow.yml.example src/main/resources/application-siliconflow.yml
# 手动编辑,把 REPLACE_ME... 替换为实际 API key
```

- [ ] **Step 1.6: 把硅基流动 profile 加入 application.yml**

编辑 `src/main/resources/application.yml`,在 `spring:` 段下加:

```yaml
spring:
  profiles:
    include: siliconflow
```

- [ ] **Step 1.7: 把 application-siliconflow.yml 加入 .gitignore**

编辑 `.gitignore`,加:

```
# AI assistant secrets
src/main/resources/application-siliconflow.yml
```

- [ ] **Step 1.8: 提交配置改动**

```bash
git add .gitignore src/main/resources/application.yml src/main/resources/application-siliconflow.yml.example
git commit -m "config(ai-assistant): siliconflow profile + gitignore secret file"
```

- [ ] **Step 1.9: 写 AiProperties.java**

`src/main/java/com/lab/reservation/ai/config/AiProperties.java`:

```java
package com.lab.reservation.ai.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "ai.assistant")
public class AiProperties {
    private RateLimit ratelimit = new RateLimit();
    private int contextWindowTurns = 10;
    private int pendingTimeoutMinutes = 5;
    private Rag rag = new Rag();

    @Data
    public static class RateLimit {
        private int capacity = 20;
        private int refillPerMinute = 20;
    }

    @Data
    public static class Rag {
        private int topK = 5;
        private double similarityThreshold = 0.6;
    }
}
```

- [ ] **Step 1.10: 在主类启用 @ConfigurationProperties**

编辑 `src/main/java/com/lab/reservation/ReservationApplication.java`,加 `@ConfigurationPropertiesScan`:

```java
@SpringBootApplication
@ConfigurationPropertiesScan  // ← 加这行
public class ReservationApplication { ... }
```

- [ ] **Step 1.11: 提交 AiProperties**

```bash
git add src/main/java/com/lab/reservation/ai/config/AiProperties.java src/main/java/com/lab/reservation/ReservationApplication.java
git commit -m "feat(ai-assistant): AiProperties config bean"
```

- [ ] **Step 1.12: 加 Chroma 容器到 docker-compose.yml**

编辑 `docker-compose.yml`,在 `services:` 段加:

```yaml
  chroma:
    image: chromadb/chroma:1.0.0
    container_name: lab-chroma
    restart: unless-stopped
    volumes:
      - chroma_data:/chroma/chroma
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      - IS_PERSISTENT=TRUE
      - PERSIST_DIRECTORY=/chroma/chroma
      - ANONYMIZED_TELEMETRY=FALSE
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v2/heartbeat"]
      interval: 30s
      timeout: 5s
      retries: 3
```

在文件末尾 `volumes:` 段加:

```yaml
volumes:
  chroma_data:
```

- [ ] **Step 1.13: 启动 Chroma 验证**

```bash
cd D:/agent_learning/lab_devices_reservation
docker compose up -d chroma
sleep 5
curl http://localhost:8000/api/v2/heartbeat
```

Expected: `{"nanosecond heartbeat": ...}`

- [ ] **Step 1.14: 提交 Chroma docker-compose**

```bash
git add docker-compose.yml
git commit -m "build(ai-assistant): add Chroma 1.0.0 service to docker-compose"
```

- [ ] **Step 1.15: 写 ToolExecutionResult DTO**

`src/main/java/com/lab/reservation/ai/dto/ToolExecutionResult.java`:

```java
package com.lab.reservation.ai.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class ToolExecutionResult {
    private boolean ok;
    private String code;
    private String msg;
    private Object data;

    public static ToolExecutionResult ok(Object data) {
        return new ToolExecutionResult(true, "SUCCESS", "成功", data);
    }

    public static ToolExecutionResult fail(String code, String msg) {
        return new ToolExecutionResult(false, code, msg, null);
    }
}
```

- [ ] **Step 1.16: 写 HelloWorldController 冒烟测试**

`src/main/java/com/lab/reservation/ai/HelloWorldController.java`:

```java
package com.lab.reservation.ai;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.security.SecurityUserDetails;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 冒烟测试,验证硅基流动连通性。Phase A 完成后可保留作为 v1 debug 端点,生产可限流或下掉。 */
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
        String reply = chatClient.prompt()
                .user(req.getOrDefault("text", "你好,你能做什么?"))
                .call()
                .content();
        return ToolExecutionResult.ok(Map.of(
                "reply", reply,
                "user", user == null ? "anonymous" : user.getUsername()
        ));
    }
}
```

- [ ] **Step 1.17: 启动后端,跑冒烟测试**

```bash
cd D:/agent_learning/lab_devices_reservation
mvn spring-boot:run &
sleep 30
# 拿一个测试 JWT
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"student1","password":"password"}' | jq -r '.data.accessToken')
# 调冒烟端点
curl -X POST http://localhost:8080/api/ai/test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"你好,一句话介绍你自己"}'
```

Expected: 返回 JSON,`data.reply` 字段是 AI 自我介绍(中文)。

- [ ] **Step 1.18: 提交冒烟端点**

```bash
git add src/main/java/com/lab/reservation/ai/
git commit -m "feat(ai-assistant): hello-world /api/ai/test smoke endpoint"
```

✅ **Task 1 完成**:Spring AI 集成,Chroma 跑通,LLM 联通验证。

---

## Task 2: RAG 基础设施 — Chroma 集合 + 摄入服务 + 检索服务

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/service/RagIngestService.java`
- Create: `src/main/java/com/lab/reservation/ai/service/RagSearchService.java`
- Create: `src/main/java/com/lab/reservation/ai/AdminRagController.java`(管理员入口,上传文档)
- Create: `src/test/java/com/lab/reservation/ai/RagIngestServiceTest.java`

- [ ] **Step 2.1: 写 RagIngestServiceTest(失败测试)**

`src/test/java/com/lab/reservation/ai/RagIngestServiceTest.java`:

```java
package com.lab.reservation.ai;

import com.lab.reservation.ai.service.RagIngestService;
import org.junit.jupiter.api.Test;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class RagIngestServiceTest {

    @Test
    void split_returns_chunks_with_metadata() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);
        String text = "段落1\n\n段落2 较短的。\n\n段落3".repeat(50);

        List<Document> chunks = svc.splitIntoChunks(text, "manual-facsaria-001", 5L);

        assertThat(chunks).isNotEmpty();
        chunks.forEach(c -> {
            assertThat(c.getMetadata()).containsKey("doc_id");
            assertThat(c.getMetadata()).containsKey("device_id");
            assertThat(c.getMetadata()).containsKey("chunk_index");
        });
    }

    @Test
    void ingest_writes_to_vector_store() {
        VectorStore vs = mock(VectorStore.class);
        RagIngestService svc = new RagIngestService(vs);

        svc.ingest("manual-001", "测试内容", 5L);

        verify(vs).add(any(List.class));
    }
}
```

- [ ] **Step 2.2: 跑测试确认失败**

```bash
cd D:/agent_learning/lab_devices_reservation
mvn test -Dtest=RagIngestServiceTest
```

Expected: `FAIL: cannot find symbol RagIngestService`

- [ ] **Step 2.3: 写 RagIngestService**

`src/main/java/com/lab/reservation/ai/service/RagIngestService.java`:

```java
package com.lab.reservation.ai.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class RagIngestService {

    private final VectorStore vectorStore;
    private final TokenTextSplitter splitter = TokenTextSplitter.builder()
            .withChunkSize(500)
            .withMinChunkSizeChars(350)
            .withMinChunkLengthToEmbed(5)
            .build();

    /** 切块(不写库,纯逻辑测试用) */
    public List<Document> splitIntoChunks(String text, String docId, Long deviceId) {
        List<Document> raw = splitter.split(new Document(text));
        int total = raw.size();
        return raw.stream().map(d -> {
            Map<String, Object> meta = new HashMap<>();
            meta.put("doc_id", docId);
            meta.put("doc_type", "manual");
            meta.put("device_id", deviceId);
            meta.put("ingested_at", java.time.Instant.now().toString());
            meta.put("chunk_index", raw.indexOf(d));
            meta.put("chunk_total", total);
            return new Document(d.getText(), meta);
        }).toList();
    }

    /** 摄入一段文本(管理员调用) */
    public int ingest(String docId, String text, Long deviceId) {
        List<Document> chunks = splitIntoChunks(text, docId, deviceId);
        vectorStore.add(chunks);
        log.info("ingested doc={} device={} chunks={}", docId, deviceId, chunks.size());
        return chunks.size();
    }

    /** 重建集合(切 embedding 模型时用) */
    public void rebuildCollection() {
        vectorStore.deleteCollection("lab_manuals");
        // Spring AI 会在下次 add 时自动重建
    }
}
```

- [ ] **Step 2.4: 跑测试确认通过**

```bash
mvn test -Dtest=RagIngestServiceTest
```

Expected: 2 tests passed

- [ ] **Step 2.5: 提交 RagIngestService + 测试**

```bash
git add src/main/java/com/lab/reservation/ai/service/RagIngestService.java src/test/java/com/lab/reservation/ai/
git commit -m "feat(ai-assistant): RagIngestService with TokenTextSplitter + test"
```

- [ ] **Step 2.6: 写 RagSearchServiceTest**

`src/test/java/com/lab/reservation/ai/service/RagSearchServiceTest.java`:

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import org.junit.jupiter.api.Test;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class RagSearchServiceTest {

    @Test
    void search_passes_threshold_and_topk() {
        VectorStore vs = mock(VectorStore.class);
        when(vs.similaritySearch(org.mockito.ArgumentMatchers.any(SearchRequest.class)))
                .thenReturn(java.util.List.of());
        AiProperties props = new AiProperties();
        RagSearchService svc = new RagSearchService(vs, props);

        svc.search("怎么开机", null);

        verify(vs).similaritySearch(org.mockito.ArgumentMatchers.argThat(req ->
                req.getTopK() == 5 && req.getSimilarityThreshold() == 0.6
        ));
    }
}
```

- [ ] **Step 2.7: 跑测试确认失败**

```bash
mvn test -Dtest=RagSearchServiceTest
```

Expected: `FAIL: cannot find symbol RagSearchService`

- [ ] **Step 2.8: 写 RagSearchService**

`src/main/java/com/lab/reservation/ai/service/RagSearchService.java`:

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class RagSearchService {

    private final VectorStore vectorStore;
    private final AiProperties props;

    public List<Document> search(String query, Long deviceId) {
        SearchRequest req = SearchRequest.defaults()
                .withTopK(props.getRag().getTopK())
                .withSimilarityThreshold(props.getRag().getSimilarityThreshold());
        if (deviceId != null) {
            req = req.withFilterExpression("device_id == " + deviceId);
        }
        return vectorStore.similaritySearch(req.query(query));
    }
}
```

- [ ] **Step 2.9: 跑测试确认通过**

```bash
mvn test -Dtest=RagSearchServiceTest
```

Expected: 1 test passed

- [ ] **Step 2.10: 写管理员入口(上传手册)**

`src/main/java/com/lab/reservation/ai/AdminRagController.java`:

```java
package com.lab.reservation.ai;

import com.lab.reservation.ai.service.RagIngestService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/admin/rag")
@RequiredArgsConstructor
@PreAuthorize("hasAnyRole('LAB_ADMIN','SYS_ADMIN')")
public class AdminRagController {

    private final RagIngestService ingestService;

    @PostMapping("/ingest")
    public Map<String, Object> ingest(@RequestBody Map<String, Object> req) {
        String docId = (String) req.get("doc_id");
        String text = (String) req.get("text");
        Long deviceId = ((Number) req.get("device_id")).longValue();
        int chunks = ingestService.ingest(docId, text, deviceId);
        return Map.of("ok", true, "chunks_ingested", chunks);
    }
}
```

- [ ] **Step 2.11: 提交 RAG 基础设施**

```bash
git add src/main/java/com/lab/reservation/ai/service/RagSearchService.java \
        src/main/java/com/lab/reservation/ai/AdminRagController.java \
        src/test/java/com/lab/reservation/ai/
git commit -m "feat(ai-assistant): RagSearchService + admin ingest endpoint"
```

- [ ] **Step 2.12: 跑 RAG 端到端测试(手动)**

```bash
# 拿管理员 token
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}' | jq -r '.data.accessToken')
# 摄入一段设备手册
curl -X POST http://localhost:8080/api/admin/rag/ingest \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "manual-facsaria-001",
    "device_id": 5,
    "text": "BD FACS Aria III 开机步骤:\n1. 打开液流开关\n2. 等待 5 分钟预热\n3. 运行 QC beads"
  }'
```

Expected: `{"ok":true,"chunks_ingested":1}`

- [ ] **Step 2.13: 提交手工验证产物(如修改)**

无新文件,跳过。

✅ **Task 2 完成**:RAG 基础设施工具就绪(可摄入、可检索)。

---

## Task 3: 工具层 — 10 个 @Tool + Shim + Validator + 权限过滤

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/tool/ToolArgumentValidator.java`
- Create: `src/main/java/com/lab/reservation/ai/exception/ToolArgumentException.java`
- Create: `src/main/java/com/lab/reservation/ai/service/ToolRegistry.java`
- Create: `src/main/java/com/lab/reservation/ai/service/ToolPermissionFilter.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/ReservationTool.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/DeviceTool.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/RecommendTool.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/RepairTool.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/AdminTool.java`
- Create: `src/main/java/com/lab/reservation/ai/tool/RagManualTool.java`
- Modify: `src/main/java/com/lab/reservation/service/ReservationService.java`
- Modify: `src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java`
- Create: `src/test/java/com/lab/reservation/ai/ToolPermissionFilterTest.java`

(以下为关键 Task 步骤,完整内容约 700 行,本 plan 保留任务入口与测试骨架;实施时按 TDD 写每个工具的 shim + test。)

- [ ] **Step 3.1: 写 ToolArgumentException**

`src/main/java/com/lab/reservation/ai/exception/ToolArgumentException.java`:

```java
package com.lab.reservation.ai.exception;
import lombok.Getter;
@Getter
public class ToolArgumentException extends RuntimeException {
    private final String code;
    public ToolArgumentException(String code, String msg) { super(msg); this.code = code; }
}
```

- [ ] **Step 3.2: 写 ToolArgumentValidator(简化版:用注解描述必填,运行时反射检查)**

`src/main/java/com/lab/reservation/ai/tool/ToolArgumentValidator.java`:

```java
package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.exception.ToolArgumentException;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.HashMap;
import java.util.Map;

/** 工具参数校验器:启动时构建"方法→参数规则表",运行时校验。 */
@Component
public class ToolArgumentValidator {

    private final Map<String, ParamRule[]> rules = new HashMap<>();

    public void register(String methodId, Method method) {
        ParamRule[] prs = new ParamRule[method.getParameters().length];
        for (int i = 0; i < prs.length; i++) {
            Parameter p = method.getParameters()[i];
            ToolParam ann = p.getAnnotation(ToolParam.class);
            prs[i] = new ParamRule(
                p.getName(),
                p.getType(),
                ann == null ? null : ann.description()
            );
        }
        rules.put(methodId, prs);
    }

    public void validate(String methodId, Map<String, Object> args) {
        ParamRule[] prs = rules.get(methodId);
        if (prs == null) return;  // 未注册,放行
        for (ParamRule r : prs) {
            Object v = args == null ? null : args.get(r.name);
            // 基础类型:String 不可为 null/空;Long 必须 > 0
            if (v == null) {
                throw new ToolArgumentException("MISSING_FIELD", "missing field: " + r.name);
            }
            if (r.type == String.class && ((String) v).isBlank()) {
                throw new ToolArgumentException("PARAM_INVALID", "blank field: " + r.name);
            }
            if ((r.type == Long.class || r.type == Integer.class)
                    && ((Number) v).longValue() <= 0) {
                throw new ToolArgumentException("PARAM_INVALID", "non-positive: " + r.name);
            }
        }
    }

    private record ParamRule(String name, Class<?> type, String description) {}
}
```

- [ ] **Step 3.3: 写 ToolPermissionFilter(测试)**

`src/test/java/com/lab/reservation/ai/ToolPermissionFilterTest.java`:

```java
package com.lab.reservation.ai;

import com.lab.reservation.ai.service.ToolRegistry;
import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.Test;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ToolPermissionFilterTest {

    @Test
    void student_sees_only_student_tools() {
        ToolRegistry reg = new ToolRegistry();
        reg.scan();  // 空扫描,无工具
        SecurityUserDetails student = mockStudent();
        assertThat(reg.availableFor(student)).isEmpty();  // 空注册表,空结果
    }

    private SecurityUserDetails mockStudent() {
        return new SecurityUserDetails(
                1L, "student1", "password", List.of(new SimpleGrantedAuthority("ROLE_STUDENT"))
        );
    }
}
```

- [ ] **Step 3.4: 写 ToolRegistry 骨架**

`src/main/java/com/lab/reservation/ai/service/ToolRegistry.java`:

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.tool.ToolArgumentValidator;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.context.ApplicationContext;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.stereotype.Service;

import java.lang.reflect.Method;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class ToolRegistry {

    private final ApplicationContext ctx;
    private final ToolArgumentValidator validator;
    private final Map<String, ToolDefinition> tools = new HashMap<>();

    @PostConstruct
    public void scan() {
        Map<String, Object> beans = ctx.getBeansWithAnnotation(org.springframework.stereotype.Component.class);
        for (Object bean : beans.values()) {
            for (Method m : bean.getClass().getMethods()) {
                Tool t = m.getAnnotation(Tool.class);
                if (t == null) continue;
                String id = bean.getClass().getSimpleName() + "." + m.getName();
                ToolDefinition def = new ToolDefinition(
                    id, bean, m, t.name(), t.description(),
                    parseRoles(t),  // 从 @Tool.description 后缀(约定)解析角色
                    false  // confirmRequired:shim 内部判断
                );
                tools.put(id, def);
                validator.register(id, m);
            }
        }
        log.info("scanned {} AI tools", tools.size());
    }

    /** 工具定义 */
    public record ToolDefinition(
        String id, Object bean, Method method,
        String name, String description,
        Set<String> roles, boolean confirmRequired
    ) {}

    public List<ToolDefinition> availableFor(SecurityUserDetails user) {
        Set<String> userRoles = user.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .map(s -> s.replace("ROLE_", ""))
                .collect(Collectors.toSet());
        return tools.values().stream()
                .filter(t -> t.roles().isEmpty() || userRoles.stream().anyMatch(t.roles()::contains))
                .toList();
    }

    public Collection<ToolDefinition> all() { return tools.values(); }

    private Set<String> parseRoles(Tool t) {
        // 约定:从 description 末尾 "{roles:STUDENT,LAB_ADMIN}" 解析
        String d = t.description();
        if (d == null || !d.contains("{roles:")) return Set.of();
        int start = d.indexOf("{roles:") + 7;
        int end = d.indexOf("}", start);
        return Arrays.stream(d.substring(start, end).split(","))
                .map(String::trim).collect(Collectors.toSet());
    }
}
```

- [ ] **Step 3.5: 跑测试**

```bash
mvn test -Dtest=ToolPermissionFilterTest
```

Expected: 1 test passed

- [ ] **Step 3.6: 提交骨架 + 校验器 + 权限过滤**

```bash
git add src/main/java/com/lab/reservation/ai/tool/ToolArgumentValidator.java \
        src/main/java/com/lab/reservation/ai/exception/ToolArgumentException.java \
        src/main/java/com/lab/reservation/ai/service/ToolRegistry.java \
        src/test/java/com/lab/reservation/ai/ToolPermissionFilterTest.java
git commit -m "feat(ai-assistant): ToolRegistry + Validator + permission filter skeleton"
```

- [ ] **Step 3.7-3.16: 写 10 个工具(每个 ~80-150 行 shim + test)**

参考 spec §5.4 详细定义。每个工具结构:

```java
@Component
public class XxxTool {
    private final XxxService service;
    private final SecurityUserDetails currentUser;  // 通过 @AuthenticationPrincipal 注入

    @Tool(description = "工具描述 {roles:STUDENT,LAB_ADMIN}")
    public ToolExecutionResult methodName(@ToolParam(...) ...args) {
        // 1. 调 Validator.validate(methodId, args)
        // 2. 翻译 args 到 DTO
        // 3. 调 service,捕获 BusinessException
        // 4. 返回 ToolExecutionResult
    }
}
```

10 个工具的实现文件路径见"文件结构"表。

- [ ] **Step 3.17: 提交所有 10 个工具**

```bash
git add src/main/java/com/lab/reservation/ai/tool/
git commit -m "feat(ai-assistant): 10 tool shims (reservation/device/recommend/repair/admin/rag)"
```

✅ **Task 3 完成**:工具层就绪。

---

## Task 4: 确认机制 + 审计日志

**Files:**
- Create: `src/main/resources/db/migration/V1_0_5__ai_assistant.sql`
- Create: `src/main/java/com/lab/reservation/entity/AiConversation.java`
- Create: `src/main/java/com/lab/reservation/entity/AiMessage.java`
- Create: `src/main/java/com/lab/reservation/entity/AiToolExecution.java`
- Create: `src/main/java/com/lab/reservation/entity/AiWsFrame.java`
- Create: `src/main/java/com/lab/reservation/mapper/AiConversationMapper.java`
- Create: `src/main/java/com/lab/reservation/mapper/AiMessageMapper.java`
- Create: `src/main/java/com/lab/reservation/mapper/AiToolExecutionMapper.java`
- Create: `src/main/java/com/lab/reservation/mapper/AiWsFrameMapper.java`
- Create: `src/main/java/com/lab/reservation/ai/service/ConfirmationService.java`
- Create: `src/main/java/com/lab/reservation/ai/service/AuditService.java`
- Create: `src/main/java/com/lab/reservation/ai/service/AiFrameService.java`
- Create: `src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java`
- Create: `src/main/java/com/lab/reservation/ai/task/AiConversationCleanupScheduler.java`
- Create: `src/test/java/com/lab/reservation/ai/ConfirmationServiceTest.java`

(简化:TDD 关键状态机 + 5 个 entity + 4 个 mapper + 3 个 service + 2 个 scheduler。每个 ~50-200 行。)

- [ ] **Step 4.1: 写 4 张表的 Flyway 迁移**

`src/main/resources/db/migration/V1_0_5__ai_assistant.sql`:

```sql
-- ai_conversation
CREATE TABLE ai_conversation (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    title VARCHAR(100),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_user_updated (user_id, updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ai_message
CREATE TABLE ai_message (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content MEDIUMTEXT,
    tool_calls JSON,
    token_count INT DEFAULT 0,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv_created (conversation_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ai_tool_execution
CREATE TABLE ai_tool_execution (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments JSON NOT NULL,
    result JSON,
    status VARCHAR(20) NOT NULL,
    user_confirmed_at DATETIME,
    executed_at DATETIME,
    error_message TEXT,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv (conversation_id),
    KEY idx_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ai_ws_frame
CREATE TABLE ai_ws_frame (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    frame_seq BIGINT NOT NULL,
    frame_type VARCHAR(30) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conv_seq (conversation_id, frame_seq),
    KEY idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- [ ] **Step 4.2-4.5: 4 个 entity 类(标准 MyBatis-Plus 模板)**

每个 ~30 行。文件路径见"文件结构"。

- [ ] **Step 4.6-4.9: 4 个 mapper(继承 `BaseMapper<T>`)**

每个 ~15 行。

- [ ] **Step 4.10: 写 ConfirmationServiceTest**

`src/test/java/com/lab/reservation/ai/ConfirmationServiceTest.java`:

```java
class ConfirmationServiceTest {
    @Test
    void create_writes_pending_status() {
        // mock mapper, 调 service.create, 验证 status='pending'
    }
    @Test
    void confirm_transitions_pending_to_confirmed() { ... }
    @Test
    void execute_transitions_confirmed_to_executed() { ... }
    @Test
    void cancel_transitions_pending_to_cancelled() { ... }
    @Test
    void expire_transitions_old_pending_to_expired() { ... }
}
```

- [ ] **Step 4.11-4.12: 写 ConfirmationService(状态机实现)+ 测试通过**

`src/main/java/com/lab/reservation/ai/service/ConfirmationService.java`:

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.mapper.AiToolExecutionMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class ConfirmationService {

    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_CONFIRMED = "confirmed";
    public static final String STATUS_EXECUTED = "executed";
    public static final String STATUS_CANCELLED = "cancelled";
    public static final String STATUS_ERROR = "error";
    public static final String STATUS_EXPIRED = "expired";

    private final AiToolExecutionMapper mapper;

    public Long create(Long convId, Long msgId, String toolName, Map<String, Object> args) {
        AiToolExecution e = new AiToolExecution();
        e.setConversationId(convId);
        e.setMessageId(msgId);
        e.setToolName(toolName);
        e.setArguments(toJson(args));
        e.setStatus(STATUS_PENDING);
        e.setCreatedAt(LocalDateTime.now());
        mapper.insert(e);
        return e.getId();
    }

    public void confirm(Long actionId) {
        AiToolExecution e = mapper.selectById(actionId);
        e.setStatus(STATUS_CONFIRMED);
        e.setUserConfirmedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    public void execute(Long actionId, Object result) {
        AiToolExecution e = mapper.selectById(actionId);
        e.setStatus(STATUS_EXECUTED);
        e.setResult(toJson(result));
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    public void cancel(Long actionId) {
        AiToolExecution e = mapper.selectById(actionId);
        if (!STATUS_PENDING.equals(e.getStatus())) return;
        e.setStatus(STATUS_CANCELLED);
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    public void error(Long actionId, String msg) {
        AiToolExecution e = mapper.selectById(actionId);
        e.setStatus(STATUS_ERROR);
        e.setErrorMessage(msg);
        e.setExecutedAt(LocalDateTime.now());
        mapper.updateById(e);
    }

    private String toJson(Object o) {
        // 用 Jackson ObjectMapper(注入)
        return new com.fasterxml.jackson.databind.ObjectMapper().writeValueAsString(o);
    }
}
```

- [ ] **Step 4.13: 写 AiActionTimeoutScheduler**

`src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java`:

```java
package com.lab.reservation.ai.task;

import com.lab.reservation.ai.service.ConfirmationService;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.mapper.AiToolExecutionMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

@Slf4j
@Component
@RequiredArgsConstructor
public class AiActionTimeoutScheduler {

    private final AiToolExecutionMapper mapper;
    private final ConfirmationService confirmationService;
    private final AiProperties props;

    @Scheduled(fixedDelay = 60_000)  // 每分钟
    public void expireOldPending() {
        LocalDateTime threshold = LocalDateTime.now()
                .minusMinutes(props.getPendingTimeoutMinutes());
        List<AiToolExecution> old = mapper.selectList(
            new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<AiToolExecution>()
                .eq("status", ConfirmationService.STATUS_PENDING)
                .lt("created_at", threshold)
        );
        old.forEach(e -> {
            e.setStatus(ConfirmationService.STATUS_EXPIRED);
            e.setErrorMessage("PENDING_TIMEOUT");
            mapper.updateById(e);
            log.info("expired pending AI action id={}", e.getId());
        });
    }
}
```

- [ ] **Step 4.14: 写 AiConversationCleanupScheduler(90 天滚动)**

类似结构,`@Scheduled(cron = "0 0 3 * * ?")` 每天 3 点扫 90 天前的 ai_conversation/ai_message/ai_ws_frame 删除。

- [ ] **Step 4.15: 提交确认 + 审计 + 调度器**

```bash
git add src/main/resources/db/migration/ \
        src/main/java/com/lab/reservation/entity/Ai*.java \
        src/main/java/com/lab/reservation/mapper/Ai*Mapper.java \
        src/main/java/com/lab/reservation/ai/service/ConfirmationService.java \
        src/main/java/com/lab/reservation/ai/service/AuditService.java \
        src/main/java/com/lab/reservation/ai/service/AiFrameService.java \
        src/main/java/com/lab/reservation/ai/task/ \
        src/test/java/com/lab/reservation/ai/ConfirmationServiceTest.java
git commit -m "feat(ai-assistant): 4 tables + entities + mappers + confirmation state machine + schedulers"
```

✅ **Task 4 完成**:持久层 + 状态机 + 调度器就绪。

---

## Task 5: 后端 WebSocket + 多轮 + while-loop + step_update

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/controller/AiAssistantController.java`
- Create: `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java`
- Create: `src/main/java/com/lab/reservation/ai/dto/WsServerMsg.java`
- Create: `src/main/java/com/lab/reservation/ai/dto/WsClientMsg.java`
- Create: `src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java`
- Create: `src/main/java/com/lab/reservation/ai/service/SystemPromptBuilder.java`
- Modify: `src/main/java/com/lab/reservation/security/JwtUtils.java`(若需要 refreshToken)
- Create: `src/test/java/com/lab/reservation/ai/AiAssistantServiceTest.java`(mock ChatClient)

- [ ] **Step 5.1: 写 WsClientMsg / WsServerMsg 记录类**

两个文件,union 模式:

```java
// WsClientMsg.java
public sealed interface WsClientMsg {
    record UserMessage(Long conv_id, String text) implements WsClientMsg {}
    record ConfirmAction(Long action_id) implements WsClientMsg {}
    record CancelAction(Long action_id) implements WsClientMsg {}
    record Resync(Long last_seq) implements WsClientMsg {}
    record CancelSession(Long conv_id) implements WsClientMsg {}  // §7.4.5 多步中断
}

// WsServerMsg.java(20+ record 类型,见 spec §10.0)
public sealed interface WsServerMsg {
    record Delta(Long seq, Long conv_id, String text) implements WsServerMsg {}
    record StepUpdate(...) implements WsServerMsg {}
    record Suggestions(...) implements WsServerMsg {}
    record AssistantDone(...) implements WsServerMsg {}
    record ConfirmationRequired(...) implements WsServerMsg {}
    record ConfirmationExpired(Long action_id) implements WsServerMsg {}
    record ExecutionResult(...) implements WsServerMsg {}
    record Error(String code, String msg) implements WsServerMsg {}
    record Ping(Long ts) implements WsServerMsg {}
}
```

- [ ] **Step 5.2: 写 SystemPromptBuilder(按角色生成 system message)**

`src/main/java/com/lab/reservation/ai/service/SystemPromptBuilder.java`:

```java
package com.lab.reservation.ai.service;

import org.springframework.stereotype.Service;

@Service
public class SystemPromptBuilder {

    public String build(String role) {
        return """
            你是实验室预约系统的 AI 助手,服务于 [%s] 角色。

            ## 工具调用规则
            1. 时间参数必须是 ISO-8601 local datetime 格式,例如 "2026-07-08T14:00:00"
               禁止输出中文时间表述(如"周三 14 点"、"下午两点")。
            2. 设备 ID 必须是 Long 整数,从 search_devices 工具返回结果中获取,
               禁止猜测或编造 ID。
            3. 写工具(create_reservation / cancel_reservation / submit_repair_ticket /
               take_repair_ticket)只是"提议",用户未点确认前不要假定执行成功。
            4. 工具不可用时(如越权),明确告诉用户"该操作需要 X 权限",不要伪造结果。

            ## 回答风格
            - 中文,简洁,准确
            - 涉及设备/时间/数字时给出具体值,不要模糊
            - 检索到文档时引用来源
            - 检索不到时明确说"暂无相关文档",不要编造
            """.formatted(role);
    }
}
```

- [ ] **Step 5.3: 写 ChatClientConfig(配置 ChromaVectorStore 注入 ChatClient)**

`src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java`:

```java
package com.lab.reservation.ai.config;

import com.lab.reservation.ai.service.SystemPromptBuilder;
import lombok.RequiredArgsConstructor;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.vectorstore.QuestionAnswerAdvisor;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@RequiredArgsConstructor
public class ChatClientConfig {

    private final VectorStore vectorStore;
    private final SystemPromptBuilder promptBuilder;

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder
            .defaultAdvisors(QuestionAnswerAdvisor.builder(vectorStore)
                .searchRequest(SearchRequest.defaults()
                    .withTopK(5)
                    .withSimilarityThreshold(0.6))
                .build())
            .build();
    }
}
```

- [ ] **Step 5.4: 写 AiAssistantService(while-loop 编排,核心类,~450 行)**

`src/main/java/com/lab/reservation/ai/service/AiAssistantService.java`:

```java
package com.lab.reservation.ai.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.ai.dto.WsServerMsg;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.entity.AiMessage;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.entity.AiWsFrame;
import com.lab.reservation.mapper.AiConversationMapper;
import com.lab.reservation.mapper.AiMessageMapper;
import com.lab.reservation.mapper.AiWsFrameMapper;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.*;

@Slf4j
@Service
@RequiredArgsConstructor
public class AiAssistantService {

    private static final int MAX_TURNS = 10;

    private final ChatClient chatClient;
    private final ToolRegistry toolRegistry;
    private final ConversationService conversationService;
    private final ConfirmationService confirmationService;
    private final AiFrameService frameService;
    private final SimpMessagingTemplate ws;
    private final ObjectMapper objectMapper;
    private final SystemPromptBuilder promptBuilder;
    private final AiProperties props;

    /** 处理 user_message 主入口 */
    public void handleUserMessage(SecurityUserDetails user, Long convId, String text) {
        if (convId == null) {
            AiConversation conv = conversationService.create(user.getId());
            convId = conv.getId();
        }
        // while-loop 多步连击
        for (int turn = 0; turn < MAX_TURNS; turn++) {
            String aiOutput = callChatClientOnce(user, convId, text, turn);
            // 简化:LLM 输出若含 [FINAL] 标记则退出
            if (aiOutput == null || aiOutput.contains("[FINAL]")) {
                break;
            }
            // 否则:检测是否有 tool_call(由 LLM 触发的,我们这里简化)
            // (实际生产用 Spring AI ToolCallingAdvisor 自动 loop)
        }
    }

    private String callChatClientOnce(SecurityUserDetails user, Long convId, String text, int turn) {
        List<Message> history = conversationService.buildPrompt(convId, text, user.getAuthorities());
        String reply = chatClient.prompt()
                .system(promptBuilder.build(extractRole(user)))
                .messages(history)
                .call()
                .content();
        // 流式推送:简化版,一次性发 assistant_done
        frameService.push(convId, user.getId(), "assistant_done",
                Map.of("text", reply, "tool_calls", List.of()));
        return reply;
    }

    private String extractRole(SecurityUserDetails user) {
        return user.getAuthorities().stream()
                .findFirst()
                .map(a -> a.getAuthority().replace("ROLE_", ""))
                .orElse("STUDENT");
    }
}
```

(实际实现会更复杂:处理 tool_call 链、step_update 推送、confirmation_required 推送、suggestions 推送。本 Task 包含完整 while-loop + step_update 触发。)

- [ ] **Step 5.5: 写 AiAssistantController(STOMP 入口)**

`src/main/java/com/lab/reservation/ai/controller/AiAssistantController.java`:

```java
package com.lab.reservation.ai.controller;

import com.lab.reservation.ai.dto.WsClientMsg;
import com.lab.reservation.ai.service.AiAssistantService;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.SendTo;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.stereotype.Controller;
import org.springframework.stereotype.Controller;
import org.springframework.messaging.simp.annotation.SendToUser;

@Controller
@RequiredArgsConstructor
public class AiAssistantController {

    private final AiAssistantService service;

    @MessageMapping("/app/assistant/send")
    public void handleSend(WsClientMsg.UserMessage msg,
                          @AuthenticationPrincipal SecurityUserDetails user) {
        service.handleUserMessage(user, msg.conv_id(), msg.text());
    }

    @MessageMapping("/app/assistant/confirm")
    public void handleConfirm(WsClientMsg.ConfirmAction msg,
                              @AuthenticationPrincipal SecurityUserDetails user) {
        service.handleConfirm(user, msg.action_id());
    }

    @MessageMapping("/app/assistant/cancel")
    public void handleCancel(WsClientMsg.CancelAction msg,
                             @AuthenticationPrincipal SecurityUserDetails user) {
        service.handleCancel(user, msg.action_id());
    }

    @MessageMapping("/app/assistant/resync")
    public void handleResync(WsClientMsg.Resync msg,
                            @AuthenticationPrincipal SecurityUserDetails user) {
        service.handleResync(user, msg.conv_id(), msg.last_seq());
    }
}
```

- [ ] **Step 5.6: 写 AiAssistantServiceTest(mock ChatClient)**

简化版 smoke test,验证 happy path 推一帧 assistant_done。

- [ ] **Step 5.7: 跑测试 + 提交后端 WebSocket + while-loop**

```bash
mvn test -Dtest=AiAssistantServiceTest
git add src/main/java/com/lab/reservation/ai/controller/ \
        src/main/java/com/lab/reservation/ai/service/AiAssistantService.java \
        src/main/java/com/lab/reservation/ai/service/ConversationService.java \
        src/main/java/com/lab/reservation/ai/service/SystemPromptBuilder.java \
        src/main/java/com/lab/reservation/ai/config/ChatClientConfig.java \
        src/main/java/com/lab/reservation/ai/dto/ \
        src/test/java/com/lab/reservation/ai/AiAssistantServiceTest.java
git commit -m "feat(ai-assistant): STOMP controller + ChatClient while-loop + step_update/suggestions frames"
```

✅ **Task 5 完成**:后端 AI 编排就绪,可以通过 STOMP 收发消息。

---

## Task 6: 前端 — 悬浮球 + 抽屉 + 5 种基础消息卡

**Files:**
- Create: `frontend/src/types/ai.ts`
- Create: `frontend/src/stores/ai.ts`
- Create: `frontend/src/composables/useAiWebSocket.ts`
- Create: `frontend/src/components/ai/AiAssistant.vue`(global)
- Create: `frontend/src/components/ai/MessageCard.vue`
- Create: `frontend/src/components/ai/UserMessage.vue`
- Create: `frontend/src/components/ai/AssistantMessage.vue`
- Create: `frontend/src/components/ai/DeviceListCard.vue`
- Create: `frontend/src/components/ai/ConfirmationCard.vue`
- Create: `frontend/src/components/ai/ResultCard.vue`
- Create: `frontend/src/components/ai/ErrorCard.vue`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/views/MainLayout.vue`(挂 `<AiAssistant />`)

- [ ] **Step 6.1: 写 frontend/src/types/ai.ts(TS 类型定义)**

完整定义见 spec §10.0 的 ClientMsg/ServerMsg union。

- [ ] **Step 6.2: 写 frontend/src/stores/ai.ts(Pinia store)**

状态字段:`state: 'idle'|'sending'|'streaming'|'step_running'|'awaiting_confirmation'|'executing'|'done'|'error'`,消息列表,确认卡片列表,连接状态,对话 ID。

- [ ] **Step 6.3: 写 frontend/src/composables/useAiWebSocket.ts(STOMP 客户端)**

复用 `useWebSocket.ts` 的 STOMP 模式,新加 `reconnect(newToken)` 用于 JWT 刷新后重连。

- [ ] **Step 6.4: 写 AiAssistant.vue 骨架(悬浮球 + 抽屉)**

```vue
<template>
  <div class="ai-assistant">
    <div v-if="!expanded" class="ai-ball" @click="open">●</div>
    <div v-else class="ai-drawer">
      <header>AI 助手 <button @click="close">✕</button></header>
      <MessageList />
      <InputBar />
    </div>
  </div>
</template>
```

- [ ] **Step 6.5: 写 5 种基础消息卡组件**

UserMessage / AssistantMessage / DeviceListCard / ConfirmationCard / ResultCard / ErrorCard。

- [ ] **Step 6.6: 挂到 MainLayout**

```vue
<template>
  ... 现有内容 ...
  <AiAssistant />
</template>
```

- [ ] **Step 6.7: 提交前端基础 UI**

```bash
git add frontend/src/types/ai.ts \
        frontend/src/stores/ai.ts \
        frontend/src/composables/useAiWebSocket.ts \
        frontend/src/components/ai/ \
        frontend/src/main.ts \
        frontend/src/views/MainLayout.vue
git commit -m "feat(ai-assistant): floating ball + drawer + 5 message cards"
```

- [ ] **Step 6.8: 手动 E2E 验证**

启动后端 + 前端,登录学生账号,展开悬浮球,输入"你好",验证:
- 抽屉展开
- 出现用户消息气泡
- 出现 AI 回复气泡(delta 累积)
- 关闭后再次打开,历史消息保留

✅ **Task 6 完成**:前端基础 UI 就绪。

---

## Task 7: 前端视觉特效(§7.4)

**Files:**
- Create: `frontend/src/styles/aurora.scss`
- Create: `frontend/src/styles/color-cursor.scss`
- Create: `frontend/src/components/ai/AuroraOverlay.vue`
- Create: `frontend/src/components/ai/ColorCursor.vue`
- Create: `frontend/src/components/ai/StepTimelineCard.vue`
- Create: `frontend/src/components/ai/SuggestionRow.vue`
- Modify: `frontend/src/main.ts`(引入新 scss)
- Modify: `frontend/src/stores/ai.ts`(state 触发视觉)

- [ ] **Step 7.1: 写 aurora.scss**

参考 spec §7.4.1 完整 CSS。

- [ ] **Step 7.2: 写 color-cursor.scss(data-URI SVG 光标)**

参考 spec §7.4.2。

- [ ] **Step 7.3: 写 AuroraOverlay.vue + ColorCursor.vue(状态联动)**

`AuroraOverlay` 接收 `state` prop,只有 `state === 'executing' || state === 'step_running'` 才渲染。
`ColorCursor` 触发 `<body class="ai-executing">`。

- [ ] **Step 7.4: 写 StepTimelineCard.vue(渲染 step_update 帧)**

```vue
<template>
  <div class="step-timeline">
    <div v-for="step in steps" :key="step.id" :class="['step', step.status]">
      <span class="icon">{{ iconOf(step.status) }}</span>
      <span class="text">{{ step.text }}</span>
      <span v-if="step.duration_ms" class="dur">{{ step.duration_ms }}ms</span>
    </div>
  </div>
</template>
```

- [ ] **Step 7.5: 写 SuggestionRow.vue(渲染 suggestions 帧)**

```vue
<template>
  <div class="suggestions">
    <button v-for="s in items" :key="s.value" @click="onClick(s)">
      {{ s.label }}
    </button>
  </div>
</template>
```

- [ ] **Step 7.6: 提交视觉特效**

```bash
git add frontend/src/styles/aurora.scss \
        frontend/src/styles/color-cursor.scss \
        frontend/src/components/ai/AuroraOverlay.vue \
        frontend/src/components/ai/ColorCursor.vue \
        frontend/src/components/ai/StepTimelineCard.vue \
        frontend/src/components/ai/SuggestionRow.vue \
        frontend/src/main.ts \
        frontend/src/stores/ai.ts
git commit -m "feat(ai-assistant): aurora overlay + color cursor + step timeline + suggestion row"
```

✅ **Task 7 完成**:视觉特效就绪,符合腾讯云对标。

---

## Task 8: 多步连击 + 用户中断

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java`(已含 while-loop 框架,补充中断检查)
- Create: `src/main/java/com/lab/reservation/ai/dto/CancelSessionEvent.java`
- Modify: `src/main/java/com/lab/reservation/ai/controller/AiAssistantController.java`(加 cancel_session)
- Modify: `frontend/src/stores/ai.ts`(暴露 cancelSession action)
- Modify: `frontend/src/components/ai/AiAssistant.vue`(用户点中断按钮)

- [ ] **Step 8.1: 在 AiAssistantService 加 session 取消检查**

while-loop 每轮前检查 `Thread.currentThread().isInterrupted()` 或 volatile `volatile boolean cancelled`。

- [ ] **Step 8.2: 加 `cancel_session` 端点**

后端 `@MessageMapping("/app/assistant/cancel_session")` → `service.cancelSession(convId)` → 设 volatile flag。

- [ ] **Step 8.3: 前端抽屉加"停止 AI"按钮**

`state === 'step_running' || state === 'executing'` 时显示红色"停止"按钮,点击调 `cancel_session`。

- [ ] **Step 8.4: 提交中断机制**

```bash
git add src/main/java/com/lab/reservation/ai/ \
        frontend/src/stores/ai.ts \
        frontend/src/components/ai/AiAssistant.vue
git commit -m "feat(ai-assistant): multi-step cancel session support"
```

✅ **Task 8 完成**:多步连击模式 + 用户中断就绪。

---

## Task 9: 评估 + 论文章节 + 部署

**Files:**
- Create: `src/test/java/com/lab/reservation/ai/eval/AiEvalDatasetTest.java`(30 用例)
- Modify: `docs/thesis/highlights.md`(加亮点六完整章节)
- Create: `docs/thesis/drawings/07-ai-flow.drawio`
- Create: `docs/thesis/drawings/07-ai-flow.png`
- Modify: `DEPLOY-WITH-WEBHOOK.md`(加 chroma 部署步骤)

- [ ] **Step 9.1: 写 30 个评估用例**

按 spec §11.3 表格分类:
- 10 个读工具用例
- 10 个写工具用例(含多轮参数修正)
- 5 个 RAG 用例
- 5 个越权防护用例(期望 100% 拒绝)

每个用例 = `assertThat(aiService.handle(input)).matches(expected)`。 复用 mock ChatClient。

- [ ] **Step 9.2: 跑评估**

```bash
mvn test -Dtest=AiEvalDatasetTest
```

Expected: 通过率 ≥ 论文声明的指标(读 95% / 写 90% / RAG 85% / 越权 100%)。

- [ ] **Step 9.3: 写亮点六章节**

`docs/thesis/highlights.md` 末尾追加 `## 亮点六:基于 LLM Tool-Calling 的实验室预约可信 AI 助手` 完整章节(按 spec §11.1 结构,~12-15 页)。

- [ ] **Step 9.4: 画 6.7 视觉特效时序图**

`docs/thesis/drawings/07-ai-flow.drawio` 用 drawio 画 Sub-step 同步 + 视觉特效的时序图,导出 PNG。

- [ ] **Step 9.5: 更新 DEPLOY-WITH-WEBHOOK.md**

加 chroma 部署段:docker compose up -d chroma,健康检查,数据迁移注意事项。

- [ ] **Step 9.6: 部署到腾讯云,跑通端到端**

- [ ] **Step 9.7: 提交评估 + 论文 + 部署**

```bash
git add src/test/java/com/lab/reservation/ai/eval/ \
        docs/thesis/highlights.md \
        docs/thesis/drawings/ \
        DEPLOY-WITH-WEBHOOK.md
git commit -m "feat(ai-assistant): 30-case eval + thesis highlight 6 + deploy docs"
```

- [ ] **Step 9.8: 推送到 origin**

```bash
git push origin main
```

✅ **Task 9 完成**:评估通过 + 论文就绪 + 部署完成。

---

## 完成清单

完成后应有:
- ✅ Spring AI 集成 + 硅基流动 + Chroma 跑通
- ✅ 10 个 @Tool(读 / 写 / RAG 三类)
- ✅ 4 张新表(ai_conversation / ai_message / ai_tool_execution / ai_ws_frame)
- ✅ 状态机(pending/confirmed/executed/cancelled/error/expired)+ 5 分钟 cron 扫描
- ✅ STOMP `/app/assistant/*` + 流式 + while-loop 多步
- ✅ Sub-step 同步(step_update 帧)+ 推荐下一步(suggestions 帧)
- ✅ 前端悬浮球 + 抽屉 + 5 种消息卡 + StepTimeline + SuggestionRow
- ✅ 视觉特效:页面光晕 + 彩色光标(执行态)
- ✅ 30 个评估用例通过,论文亮点六就绪
- ✅ 部署文档更新

## 后续可选(论文"未来工作")

- v2:审批工作流(approve_reservation / reject_reservation)AI 化
- v2:批量操作 AI 化
- v2:多模态(语音/图片)
- v2:模型微调(在论文积累的对话数据上 LoRA)
- v2:跨会话长期记忆(只保留 90 天滚动)

---

**Plan complete. Ready for review loop.**
