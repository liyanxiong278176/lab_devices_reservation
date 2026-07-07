# AI 助手(亮点六)设计 Spec

- **日期**:2026-07-07
- **承接**:阶段 1-4 已合并 main,前端 V5 科技深色重设计已合入(`feat/frontend-redesign-dark`)。Spring AI 2.0.0 + 硅基流动云端推理 + Chroma 向量库。
- **范围**:新增 AI 助手(腾讯云模式悬浮球),不改动现有 11 个 Service 实现,只在其上包 `@Tool` 注解。论文列为亮点六,**横切**前 5 个亮点。
- **分支**:`feat/ai-assistant`(从 `main` 拉)。
- **关联**:`docs/thesis/highlights.md`(前 5 亮点)、`docs/superpowers/specs/2026-07-04-frontend-redesign-design.md`(深色 UI 契约复用)。

---

## 1. 背景与动机

### 1.1 现状盘点

平台已有 5 个工程亮点(亮点一 Redisson 锁、亮点二 STOMP 推送、亮点三 混合推荐、亮点四 ECharts 驾驶舱、亮点五 RabbitMQ),工作量充足但缺一个**有差异化的、对外可见的**创新点。论文评审与答辩需要"亮点",亮点三(规则推荐)已被 Spring AI 论文生态冲击,亮点六需要更高的立意。

### 1.2 痛点回顾(deep-research 已抓到的真实吐槽)

- **学生**:热门仪器抢不到、跨校区没有统一日历、报修后无状态回执、信息不透明(空闲/占用不可见)
- **管理员**:报修手工分诊繁琐、热门仪器争抢 vs 空闲浪费、跨系统数据不打通
- **共同诉求**:自然语言入口 + 自动执行 + 可信确认 + 可追溯审计

### 1.3 产品参考

腾讯云控制台右下角的 **AI 小球** 是产品对标:
- 永远在线的悬浮入口
- 多轮对话解决使用问题
- 可读服务端状态(查询类操作)
- 可操作服务端(写操作前弹出确认卡片,用户点确认才执行)
- 失败/越权时给出明确解释

### 1.4 目标

把"实验室预约系统"包装成一个**对自然语言友好的可信 AI 助手**——用户可以说一句话完成"找设备、约设备、查 SOP、修设备"全流程,所有副作用操作前都有"AI 出卡片 → 人点确认 → 系统执行"的强约束。

---

## 2. 范围与非范围

### 2.1 v1 必做(亮点六主体)

- 悬浮球 + 抽屉式聊天 UI
- WebSocket 流式对话
- 9-10 个 `@Tool` 工具(读 / 写 / RAG 三类)
- 操作确认机制(`@ConfirmRequired` + 状态机)
- 角色级权限隔离(学生 / 实验室管理员 / 系统管理员)
- 审计日志(ai_tool_execution 表)
- 多轮对话持久化(ai_conversation + ai_message)
- RAG(设备 SOP 手册 + 历史报修工单)
- 评估实验(20-30 用例的工具调用准确率 / 确认通过率 / 延迟)
- 论文章节(亮点六)

### 2.2 v1 不做(YAGNI)

- ❌ 多模态(语音 / 图片输入)
- ❌ 跨会话长期记忆(只保留 90 天滚动)
- ❌ 模型微调(直接用硅基流动托管的 base)
- ❌ 工具自动发现 / 动态注册(静态 + 编译期注解)
- ❌ 国际化(只支持中文)
- ❌ 主动推送(AI 不主动发起对话)
- ❌ 审批工作流(approve_reservation / reject_reservation)— v2
- ❌ 批量操作(批量审批 / 批量导入)
- ❌ 用户管理(增删改查用户)— v2
- ❌ 模型 fallback / 多模型路由
- ❌ 现有 `RecommendServiceImpl` 升级(亮点三保留,AI 通过 tool-call 调用)

---

## 3. 架构

### 3.1 整体架构图

```
┌────────────────────────────────────────────────────────────┐
│ Frontend (Vue3,沿用 V5 深色 token)                          │
│                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│   │  悬浮球      │→│  抽屉        │→│  WebSocket   │    │
│   │ AiAssistant  │  │  消息卡片库  │  │ /api/ws/     │    │
│   │ .vue         │  │ (普通/设备/  │  │  assistant   │    │
│   │ (常驻右下)   │  │  确认/结果)  │  │              │    │
│   └──────────────┘  └──────────────┘  └──────┬───────┘    │
└──────────────────────────────────────────────┼──────────────┘
                                               │ (STOMP over SockJS)
┌──────────────────────────────────────────────┼──────────────┐
│ Backend (Spring Boot 3 + Spring AI 2.0)       │              │
│                                              ▼              │
│  ┌─────────────────────────────────────────────────┐        │
│  │  AiAssistantController (WebSocket)              │        │
│  └────────────────────┬────────────────────────────┘        │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────┐        │
│  │  AiAssistantService                             │        │
│  │  (ChatClient + ToolCallingAdvisor + 流式)        │        │
│  └────────────────────┬────────────────────────────┘        │
│                       │                                     │
│                       ▼                                     │
│  ┌─────────────────────────────────────────────────┐        │
│  │  ToolRegistry + PermissionFilter                │        │
│  │  ├─ ReservationTool    (学生/管理员)              │        │
│  │  ├─ DeviceTool         (学生/管理员)              │        │
│  │  ├─ RecommendTool      (学生)                    │        │
│  │  ├─ RepairTool         (学生/管理员)              │        │
│  │  ├─ AdminTool          (管理员)                   │        │
│  │  └─ RagManualTool      (学生/管理员,RAG)          │        │
│  └────────────────────┬────────────────────────────┘        │
│                       │ 调现有 service(零侵入)              │
│                       ▼                                     │
│  现有 11 个 Service:ReservationService / DeviceService /     │
│  RepairReportService / ApprovalService / RecommendService /  │
│  UserService / LabService / NotificationService / ...       │
│                                                              │
│  持久化(新增 3 张表):ai_conversation / ai_message /          │
│                      ai_tool_execution                       │
└──────────────────────────────────────────────────────────────┘

外部服务(腾讯云服务器本地 / 公网)
┌──────────────────────────────┐  ┌────────────────────────────┐
│ Chroma                       │  │ 硅基流动 API                │
│ (Docker 容器,Python)         │  │ (公网,OpenAI 兼容)         │
│ ├─ 端口 8000                  │  │ ├─ chat: deepseek-ai/      │
│ ├─ 持久卷 /data/chroma        │  │ │   DeepSeek-V4-Flash     │
│ └─ 集合:lab_manuals          │  │ └─ embedding: BAAI/       │
│    lab_repair_tickets        │  │     bge-m3 (1024-d)        │
└──────────────┬───────────────┘  └──────────┬─────────────────┘
               │                              │
               │  Spring AI VectorStore        │ Spring AI OpenAI client
               │  ChromaVectorStore            │
               │                              │
               └──────────┬───────────────────┘
                          │
              base-url: ${SILICONFLOW_BASE_URL}
              api-key:  ${SILICONFLOW_API_KEY}
```

### 3.2 模块边界(各自职责单一)

| 文件 | 职责 | 行数预估 |
|---|---|---|
| `AiAssistantController` | WebSocket `/api/ws/assistant` 端点 + 鉴权 + 消息分发 | ~150 |
| `AiAssistantService` | ChatClient 编排、流式、上下文管理 | ~300 |
| `ToolRegistry` | 启动时扫描所有 `@Tool` 注解,构建工具表 | ~100 |
| `ToolPermissionFilter` | 根据用户角色过滤可用工具集 | ~80 |
| `ConfirmationService` | 写操作的 pending/confirmed/cancelled 状态机 | ~200 |
| `ConversationService` | ai_conversation / ai_message 增删改查 | ~150 |
| `AuditService` | ai_tool_execution 写入与查询 | ~80 |
| `*Tool.java`(5-6 个) | 每个文件只声明一组相关 @Tool 工具 | 各 ~80-150 |
| `RagIngestService` | 把手册 / 工单向量化入库到 Chroma | ~150 |
| `WebSocketAuthHandler` | 复用现有 JwtHandshakeHandler 模式 | ~80 |
| 前端 `AiAssistant.vue` | 悬浮球 + 抽屉壳 | ~250 |
| 前端 `useAiStore` | Pinia store:会话/消息/连接状态 | ~150 |
| 前端 `MessageCard` 系列组件 | 5 种消息卡(普通 / 设备列表 / 确认 / 结果 / 错误) | 各 ~100-200 |
| 前端 `ai.ts` | WebSocket 客户端 + 重连 | ~120 |

---

## 4. 模型与基础设施

### 4.1 选型矩阵

| 角色 | 模型 | 部署 | 调用 | 用途 |
|---|---|---|---|---|
| 聊天 + 工具调用 | `deepseek-ai/DeepSeek-V4-Flash` | 硅基流动云端 | HTTPS (OpenAI 兼容) | 多轮对话 + 工具编排 + 摘要 |
| 文本嵌入 | `BAAI/bge-m3` | 硅基流动云端 | HTTPS (OpenAI 兼容) | RAG 文档嵌入 + 用户/设备画像 |
| 向量存储 | Chroma v0.5+ | 本地 Docker 容器 | HTTP (8000) | 文档 / 工单向量化检索 |

### 4.2 选型理由

- **DeepSeek-V4-Flash**:中文 SOTA,工具调用能力优于同尺寸 Qwen,Flash 档位延迟低、按 token 计费可控;比本地 Qwen2.5-1.5B/3B 强很多,工具调用稳定性大幅提升
- **BGE-M3**:中文嵌入标杆,多语种、长文本(8192 token)支持好,硅基流动托管免运维
- **Chroma**:Spring AI 官方 starter (`spring-ai-starter-vector-store-chroma`),Python 实现易运维,自包含 DuckDB+Parquet 持久化,适合论文规模(< 100k 文档)

### 4.3 第三方依赖清单

```xml
<!-- pom.xml 增量 -->
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-model-openai</artifactId>
</dependency>
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-starter-vector-store-chroma</artifactId>
</dependency>
<dependency>
    <groupId>org.springframework.ai</groupId>
    <artifactId>spring-ai-advisors-vector-store</artifactId>
</dependency>
```

`docker-compose.yml` 增量:

```yaml
chroma:
  image: chromadb/chroma:0.5.20
  container_name: lab-chroma
  restart: unless-stopped
  volumes:
    - chroma_data:/chroma/chroma
  ports:
    - "127.0.0.1:8000:8000"  # 仅 SSH 隧道访问,不暴露公网
  environment:
    - IS_PERSISTENT=TRUE
    - PERSIST_DIRECTORY=/chroma/chroma
    - ANONYMIZED_TELEMETRY=FALSE
```

---

## 5. 工具清单(v1 共 10 个)

### 5.1 学生可用工具(6 个)

| # | 工具名 | 类型 | 角色 | 确认 | 后端调用 |
|---|---|---|---|---|---|
| 1 | `search_devices` | 读 | 学生+管理员 | 无 | `DeviceService` 列表查询 |
| 2 | `get_device_details` | 读 | 学生+管理员 | 无 | `DeviceService` 详情 |
| 3 | `get_my_reservations` | 读 | 学生 | 无 | `ReservationService` 按用户过滤 |
| 4 | `recommend_devices` | 读 | 学生 | 无 | **复用现有** `RecommendServiceImpl` |
| 5 | `create_reservation` | 写 | 学生 | **必须** | `ReservationService.create` |
| 6 | `cancel_reservation` | 写 | 学生(自己的) | **必须** | `ReservationService.cancel` |
| 7 | `submit_repair_ticket` | 写 | 学生 | **必须** | `RepairReportService.create` |
| 8 | `search_device_manuals` | 读 RAG | 学生+管理员 | 无 | Chroma `lab_manuals` 集合 |

### 5.2 管理员额外工具(2 个)

| # | 工具名 | 类型 | 角色 | 确认 | 后端调用 |
|---|---|---|---|---|---|
| 9 | `query_lab_reservations` | 读 | 管理员 | 无 | `ReservationService` 按实验室过滤 |
| 10 | `assign_repair_ticket` | 写 | 管理员 | **必须** | `RepairReportService.assign` |

### 5.3 工具元数据示例

```java
@Component
public class ReservationTool {
    private final ReservationService reservationService;

    @Tool(description = "创建一条新的设备预约,需用户确认后执行")
    @PreAuthorize("hasAnyRole('STUDENT','LAB_ADMIN','SYS_ADMIN')")
    @ConfirmRequired(
        reason = "将创建一条新预约,占用设备某时段",
        riskSummary = "若该时段已被人预约,创建将失败"
    )
    public ReservationVO createReservation(
        @ToolParam(description = "设备 ID") Long deviceId,
        @ToolParam(description = "开始时间,ISO-8601 格式") String startTime,
        @ToolParam(description = "结束时间,ISO-8601 格式") String endTime,
        @ToolParam(description = "使用目的,不超过 100 字") String purpose
    ) {
        // 调现有 service,返回 VO
        return reservationService.create(...);
    }
}
```

---

## 6. 核心机制

### 6.1 角色级权限隔离

```java
// 启动时 ToolRegistry 扫描
@Component
public class ToolRegistry {
    private final Map<String, ToolDefinition> tools = new HashMap<>();

    @PostConstruct
    void scan() {
        // 反射扫描所有带 @Tool 的方法
        // 每个 ToolDefinition 记录:方法、注解、所需角色、是否需确认
    }

    public List<ToolDefinition> availableFor(UserPrincipal user) {
        return tools.values().stream()
            .filter(t -> t.getRoles().stream()
                .anyMatch(r -> user.getAuthorities().stream()
                    .anyMatch(a -> a.getAuthority().equals("ROLE_" + r))))
            .toList();
    }
}
```

**关键点**:`ChatClient` 注入的 `ToolCallback` 列表是**当前用户角色过滤后**的子集。SLM 根本看不到不能调的工具,工具描述都不会出现在 prompt 中,不存在"试错越权"的攻击面。

### 6.2 写操作确认状态机

```
                    ┌─────────────────┐
                    │ pending         │
                    │ (AI 提议,等用户) │
                    └────────┬────────┘
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
          ┌──────────────┐      ┌──────────────┐
          │ confirmed    │      │ cancelled    │
          │ (用户点确认)  │      │ (用户点取消)  │
          └──────┬───────┘      └──────────────┘
                 │
                 ▼
          ┌──────────────┐
          │ executing    │ (后端执行业务 service)
          └──────┬───────┘
                 │
       ┌─────────┴──────────┐
       ▼                    ▼
┌─────────────┐      ┌─────────────┐
│ executed    │      │ error       │
│ (成功)       │      │ (失败/异常)  │
└─────────────┘      └─────────────┘
```

每次状态变更都写入 `ai_tool_execution.status` 字段,审计日志完整。

### 6.3 越权防护演示

```
学生: "帮我删除张三的所有预约"
   ↓
SLM 想调 cancel_reservation(zhangsan_id, ...)
   ↓
ToolRegistry 过滤后,SLM 的工具列表里没有 cancel_reservation_for_other_user
   ↓
SLM 收到 tool_call error
   ↓
AI: "抱歉,取消其他用户的预约需要实验室管理员或系统管理员权限。
     您当前是学生身份,如需取消自己的预约请提供自己的预约 ID。"
```

### 6.4 多轮对话与上下文管理

- **持久层**:`ai_conversation` + `ai_message` 表,按 `user_id` 索引
- **上下文窗口**:每个新消息加载最近 10 轮(20 条 message)
- **关键事实摘要**:当上下文超过 8 轮时,触发一次 LLM 摘要(单独调用,费用极低),压缩为 system message 注入
- **新对话**:前端 "新建对话" 按钮,创建新 conversation 记录
- **历史查看**:抽屉顶部 "历史记录" 按钮,弹层显示该用户 90 天内的对话列表

### 6.5 RAG 实现(Spring AI QuestionAnswerAdvisor)

```java
@Bean
ChatClient chatClient(ChatModel chatModel, VectorStore vectorStore) {
    return ChatClient.builder(chatModel)
        .defaultAdvisors(
            new QuestionAnswerAdvisor(vectorStore, SearchRequest.defaults()
                .withTopK(5)
                .withFilterExpression("device_id == " + currentDeviceId))
        )
        .build();
}
```

**RAG 数据流**:
1. 用户问:"BD Aria 怎么开机?"
2. ChatClient 调用 QuestionAnswerAdvisor
3. Advisor 用 BGE-M3 把问题嵌入成 1024 维向量
4. Advisor 调 Chroma 在 `lab_manuals` 集合里检索 top-5 相似文档
5. Advisor 把文档拼到 system prompt:"基于以下文档回答:\n[doc1]\n[doc2]..."
6. 整个 prompt 发给 DeepSeek-V4-Flash
7. LLM 基于文档生成答案

---

## 7. 前端设计

### 7.1 视觉规范

- **复用 V5 深色 token**(`--accent` 青色、`--bg-surface` 等)
- 悬浮球:右下角固定,48px 圆形,`--accent` 渐变背景,带脉冲点呼吸动效
- 抽屉:右侧 380px 宽,`--bg-surface` 背景,圆角 16px
- 消息气泡:用户消息靠右 + `--accent` 渐变,AI 消息靠左 + `--bg-elevated`
- 确认卡片:`--bg-elevated` + 左侧 3px 警告色竖条 + 2 按钮(确认/取消)
- 设备列表卡片:网格布局,每项显示设备名 + 类别 + 可用时段

### 7.2 组件树

```
App.vue
└── MainLayout.vue
    ├── 现有内容(router-view)
    └── <AiAssistant />  ← 全局常驻
        ├── 悬浮球(收起态)
        └── 抽屉(展开态)
            ├── Header(标题 + 历史 + 新建 + 关闭)
            ├── MessageList(滚动到底)
            │   ├── UserMessage
            │   ├── AssistantMessage
            │   ├── DeviceListCard
            │   ├── ConfirmationCard  ← 关键
            │   ├── ResultCard
            │   └── ErrorCard
            └── InputBar(文本框 + 发送 + 状态指示)
```

### 7.3 状态机(前端)

```
idle (空状态,显示建议问题)
  → user_typing
  → sending (发送中,禁用输入)
  → streaming (AI 流式输出,逐字渲染)
  → awaiting_confirmation (显示确认卡片,等用户操作)
  → executing (用户已确认,等待后端结果)
  → done
  → error
```

---

## 8. 数据模型(新增 3 张表)

### 8.1 ai_conversation(对话)

```sql
CREATE TABLE ai_conversation (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    user_id      BIGINT       NOT NULL COMMENT '所属用户',
    title        VARCHAR(100) DEFAULT NULL COMMENT '对话标题(可空,前端可基于首条消息生成)',
    created_at   DATETIME     NOT NULL,
    updated_at   DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_user_updated (user_id, updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 8.2 ai_message(消息)

```sql
CREATE TABLE ai_message (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT       NOT NULL,
    role            VARCHAR(20)  NOT NULL COMMENT 'user|assistant|tool|system',
    content         MEDIUMTEXT   COMMENT '文本内容(可空,tool_call 时为 null)',
    tool_calls      JSON         COMMENT '[{name, args, result_json, status, error}]',
    token_count     INT          DEFAULT 0 COMMENT '本条 token 数(估算)',
    created_at      DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv_created (conversation_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 8.3 ai_tool_execution(审计日志)

```sql
CREATE TABLE ai_tool_execution (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    conversation_id   BIGINT       NOT NULL,
    message_id        BIGINT       NOT NULL COMMENT '触发本执行的 assistant 消息',
    tool_name         VARCHAR(100) NOT NULL,
    arguments         JSON         NOT NULL,
    result            JSON         COMMENT '执行后填充',
    status            VARCHAR(20)  NOT NULL COMMENT 'pending|confirmed|cancelled|executed|error',
    user_confirmed_at DATETIME     DEFAULT NULL,
    executed_at       DATETIME     DEFAULT NULL,
    error_message     TEXT         DEFAULT NULL,
    created_at        DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv (conversation_id),
    KEY idx_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 8.4 保留策略

- `ai_conversation` / `ai_message`:**90 天滚动清理**(定时任务每天扫一次)
- `ai_tool_execution`:**永久保留**(论文合规 + 审计)

### 8.5 迁移

新增 SQL 脚本:`src/main/resources/db/migration/V1_0_5__ai_assistant.sql`(承接 `V1_0_4` 之后)。

---

## 9. 配置(application-siliconflow.yml)

```yaml
# 实际密钥文件,gitignore 排除
spring:
  ai:
    openai:
      base-url: https://api.siliconflow.cn/v1
      api-key: sk-ejjwltbsgpznpzimbdlgiwypqzobuvyuzxtgtgqkgqrxmooz
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
```

**文件管理**:
- `src/main/resources/application-siliconflow.yml` — 真实密钥,**gitignore**
- `src/main/resources/application-siliconflow.yml.example` — 模板,占位符,git 提交
- `.gitignore` 增量:`application-siliconflow.yml`
- `application.yml` 增量:`spring.profiles.include: siliconflow`(默认开启)
- 密钥轮换:运维改 yml 后 `docker compose restart backend` 即可

---

## 10. 数据流(端到端一条消息)

### 10.1 正常流程(读工具)

```
[1] 用户在输入框敲字,回车
[2] useAiStore.sendMessage(text)
[3] WS 推送 {type:'user_message', conv_id, text}
[4] AiAssistantController 收到,验证 JWT,加载 conv 历史(滑动窗口 10 轮)
[5] ChatClient.prompt() 注入 system + history + 当前 user msg
[6] ToolRegistry.availableFor(user) 过滤出 8 个可用工具
[7] ChatClient.call() 调硅基流动 DeepSeek-V4-Flash(stream=true)
[8] SLM 流式返回 chunks,后端逐 chunk 推 WS
[9] SLM 输出 tool_call: search_devices({keyword:"流式", time_range:"周三 14-18"})
[10] 后端解析,ToolCallback 直接执行(读工具,无确认)
[11] 工具结果注入下一轮 context,继续调 SLM
[12] SLM 基于搜索结果生成自然语言回复
[13] WS 推 {type:'assistant_done', text, tool_calls:[...]}
[14] 前端渲染:用户消息 + AI 回复(含设备列表卡片)
```

### 10.2 写工具流程(带确认)

```
[1-7] 同上
[8] SLM 输出 tool_call: create_reservation({deviceId:5, start:"2026-07-08T14:00:00", ...})
[9] 后端解析,工具标注 @ConfirmRequired
[10] 不执行,写 ai_tool_execution(status='pending')
[11] WS 推 {type:'confirmation_required', action_id, tool_name, summary, args}
[12] 前端渲染确认卡片,显示设备名/时间/用途/风险说明
[13] 用户点"确认"
[14] 前端 WS 推 {type:'confirm_action', action_id}
[15] 后端更新 ai_tool_execution(status='confirmed', user_confirmed_at=NOW)
[16] 后端调 ReservationService.create
[17] 更新 ai_tool_execution(status='executed', result=..., executed_at=NOW)
[18] WS 推 {type:'execution_result', action_id, result}
[19] AI 自动续一句"已为您预约成功,通知已发送"
[20] 前端渲染结果卡片
```

### 10.3 越权流程

```
[1-6] 同上(假设学生)
[7] ChatClient 注入的工具列表 = 6 个学生工具(没有管理员工具)
[8] SLM 想调 assign_repair_ticket
[9] SLM 收到 tool_call error: "Tool not available"
[10] SLM 生成自然语言回复:"抱歉,分派工单是管理员权限,您当前是学生身份"
[11] WS 推 {type:'assistant_done', text}
[12] 前端渲染该解释消息
```

---

## 11. 论文落点(亮点六)

### 11.1 章节结构(预估 12-15 页)

```
6. 亮点六:基于 LLM Tool-Calling 的实验室预约可信 AI 助手
  6.1 研究动机与场景
      6.1.1 传统实验室预约系统的交互摩擦
      6.1.2 LLM-as-Agent 的兴起与可信挑战
      6.1.3 论文定位
  6.2 总体架构
      6.2.1 三层架构(工具层 / 编排层 / 表现层)
      6.2.2 关键技术选型(Spring AI + 硅基流动 + Chroma)
  6.3 工具调用机制
      6.3.1 @Tool 注解与注册中心
      6.3.2 角色级权限隔离(代码 + 截图)
      6.3.3 与前 5 个亮点的协同
  6.4 可信交互设计
      6.4.1 操作确认状态机(时序图)
      6.4.2 越权防护机制(代码 + 演示截图)
      6.4.3 完整审计日志(数据库截图)
  6.5 RAG 增强
      6.5.1 知识库构建(SOP 手册 + 历史工单)
      6.5.2 Spring AI QuestionAnswerAdvisor 集成
      6.5.3 BGE-M3 与 Chroma 部署
  6.6 多轮对话与持久化
      6.6.1 上下文管理(滑动窗口 + 摘要)
      6.6.2 90 天滚动策略
  6.7 评估实验
      6.7.1 工具调用准确率(20-30 用例)
      6.7.2 确认通过率(用户研究)
      6.7.3 端到端响应延迟(分位数统计)
      6.7.4 越权防护正确性
  6.8 与同类方案的对比
  6.9 局限与展望
```

### 11.2 与前 5 个亮点的关系

| 已有亮点 | AI 助手如何调用 |
|---|---|
| 亮点一 Redisson 锁 | `create_reservation` 自动触发锁防超约 |
| 亮点二 STOMP 推送 | 预约成功/取消后,AI 回复里同步提示"通知已发送" |
| 亮点三 混合推荐 | `recommend_devices` 直接调用 `RecommendServiceImpl` |
| 亮点四 ECharts 驾驶舱 | `query_lab_reservations` 复用 dashboard 部分查询逻辑 |
| 亮点五 RabbitMQ | `create_reservation` 提交后,after-commit 触发通知(同链路) |

**演示联动**:一次对话里 AI 同时调用亮点一(锁)+ 亮点二(WS 推送)+ 亮点三(推荐)+ 亮点五(MQ),论文里"5 个亮点 + 1 个横切"叙事闭环。

### 11.3 评估方法

- **用例集**:构造 25-30 个测试用例覆盖三类(读/写/RAG)+ 两角色(学生/管理员)
- **指标**:
  - 工具调用准确率(LLM 选对工具的比例)
  - 工具参数抽取正确率(参数与用户意图一致)
  - 端到端 P50/P95 延迟
  - 越权防护正确率(应当拒绝的请求被拒绝)
  - 用户满意度(5 真实用户 × 10 任务,李克特 5 点)
- **基线对比**:与"无 AI 的纯表单"流程对比任务完成时间

---

## 12. 演示剧本(答辩用)

### 剧本 A - 学生完整流程(3 分钟)

```
[1] "帮我找周三下午能做流式细胞仪的设备"
    AI: [设备列表卡片:3 台,周三 14-18 时段]
[2] "约 BD Aria 14-16,做 PCR 实验"
    AI: [确认卡片:设备/时间/用途/风险]
    用户: [点确认]
    AI: "已为您预约成功,通知已发送 ✓"
[3] "这台设备怎么开机?"
    AI: "根据 SOP 手册,BD Aria 开机步骤..."(RAG 检索)
```

### 剧本 B - 管理员分诊(2 分钟)

```
[1] "这周哪些设备报修最多?"
    AI: "本周 top3:激光共聚焦 5 单,PCR 仪 3 单,..."
[2] "把工单 #45 分给李工,优先级高"
    AI: [确认卡片:工单内容/处理人/优先级/影响]
    用户: [点确认]
    AI: "已分派,通知已发给李工"
```

### 剧本 C - 可信护栏(1 分钟)

```
[1] 学生:"删掉张三的所有预约"
    AI: "抱歉,删除其他用户的预约需要管理员权限..."
[2] 管理员:"把张三的所有设备标为已损坏"
    AI: [确认卡片:影响 12 条设备]
    用户: [点取消]
    AI: "已取消,未执行任何操作"
```

---

## 13. 测试与评估

### 13.1 单元测试

- `ToolRegistryTest` — 角色过滤正确性
- `ConfirmationServiceTest` — 状态机各路径
- `RagIngestServiceTest` — 文档分块、向量化
- `AuditServiceTest` — 日志写入

### 13.2 集成测试

- `AiAssistantEndToEndTest` — 模拟 WebSocket,测学生预约全流程
- `AiAssistantAdminTest` — 模拟管理员分诊全流程
- `PermissionEnforcementIT` — 越权防护(用学生 token 试调管理工具,期望拒绝)

### 13.3 评估实验数据集

- 25-30 个手工构造用例(覆盖读 / 写 / RAG / 越权)
- 5 名真实用户(Lab 同学)做用户研究,每用户 10 任务
- 记录:工具调用正确性 / 延迟 / 用户评分(1-5)

---

## 14. 部署

### 14.1 docker-compose.yml 增量

```yaml
services:
  chroma:
    image: chromadb/chroma:0.5.20
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
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  chroma_data:
```

### 14.2 环境要求

- 腾讯云服务器现有:Spring Boot 应用 + MySQL + Redis + RabbitMQ
- 新增:Chroma Docker 容器(本地,不暴露公网)
- 外网:能访问 `api.siliconflow.cn`(出方向 443 即可)

### 14.3 启动检查

```bash
# 1. Chroma 健康
curl http://localhost:8000/api/v1/heartbeat

# 2. Spring AI 硅基流动连通性(Spring Boot Actuator)
curl http://localhost:8080/actuator/health/spring-ai

# 3. 第一个 AI 请求(冒烟)
curl -X POST http://localhost:8080/api/ai/test \
  -H "Authorization: Bearer <student-jwt>" \
  -d '{"text":"hello"}'
```

---

## 15. 工作量

| 阶段 | 任务 | 天数 |
|---|---|---|
| A | 基础设施(Spring AI + Chroma + 硅基流动 + Hello World tool) | 3 |
| B | 工具层(10 个 @Tool + 反射注册 + 权限过滤) | 5 |
| C | 确认机制 + 审计日志(状态机 + ai_tool_execution) | 3 |
| D | WebSocket 流式 + 多轮上下文 | 3 |
| E | 前端悬浮球 + 抽屉 + 卡片库(V5 深色 token) | 5 |
| F | RAG(手册 / 工单向量化 + Chroma 集合) | 4 |
| G | 评估实验 + 论文章节(亮点六) | 5 |
| **合计** | | **~28 天** |

---

## 16. 风险

| 风险 | 缓解 |
|---|---|
| DeepSeek-V4-Flash tool-call 稳定性 | 阶段 A 预检(10 个工具调用测试),失败则降级到 `deepseek-ai/DeepSeek-V3.1` |
| 硅基流动服务宕机 / 限流 | 重试 3 次 + 友好降级"AI 助手暂时不可用" |
| API key 泄露 | 走独立 profile yml + .gitignore + 论文不展示 |
| 硅基流动网络延迟(腾讯云 → 公网) | 流式输出 + 90-150ms 头延迟用户可接受 |
| Chroma 容器崩 | docker restart + healthcheck + 数据持久卷 |
| 学生 AI 误调管理员工具 | 工具级 @PreAuthorize + registry 过滤,**根本不让 SLM 看到** |
| 误操作 | 确认卡片 + 审计日志 + 24h 撤销(后续可加) |
| 注入攻击(学生伪装成管理员) | JWT + Spring Security 角色认证在 AI 入口前 |
| 对话历史数据爆炸 | 90 天滚动清理,后台定时任务 |
| BGE-M3 维度(1024)变化 | 写死配置,如切换 embedding 模型需重建集合 |

---

## 17. 不做(Out of Scope)— 防止 YAGNI 蔓延

- ❌ 多模态(语音/图片)
- ❌ 模型微调 / LoRA
- ❌ 工具自动发现 / 动态注册
- ❌ 跨会话长期记忆(只 90 天滚动)
- ❌ 国际化(只中文)
- ❌ 主动推送
- ❌ 审批工作流(亮点六 v2)
- ❌ 批量操作
- ❌ 用户管理 UI
- ❌ 多模型路由 / fallback
- ❌ 现有 RecommendServiceImpl 升级
- ❌ 模型微调
- ❌ 离线模式

---

## 18. 假设与待确认

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 嵌入模型:硅基流动 BGE-M3 | ✅ 用户已确认 | |
| 2 | 聊天模型:硅基流动 DeepSeek-V4-Flash | ✅ 用户已确认 | API key 已提供 |
| 3 | 向量库:Chroma | ✅ 用户已确认 | 新增 Docker 容器 |
| 4 | 对话历史:90 天 | ✅ 用户已确认 | |
| 5 | API key:写入独立 yml profile | ✅ 用户已确认 | .gitignore 排除 + .example 模板 |
| 6 | RAG 内容:SOP 手册 + 历史报修工单 | ⏳ 默认假设 | spec review 时确认 |
| 7 | v1 工具数:10 个 | ⏳ 默认假设 | spec review 时确认 |
| 8 | 现有 RecommendServiceImpl 不升级 | ⏳ 默认假设 | spec review 时确认 |
| 9 | PostgreSQL pgvector 用不用 | ✅ 不使用 | Chroma 替代 |
| 10 | 部署服务器:腾讯云,已有公网 | ⏳ 默认假设 | 需用户确认能访问 api.siliconflow.cn |

---

**End of spec. Ready for spec review loop (subagent) → user review → writing-plans.**
