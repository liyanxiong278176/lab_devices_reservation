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
│   │ AiAssistant  │  │  消息卡片库  │  │ 复用 /api/ws │    │
│   │ .vue         │  │ (普通/设备/  │  │ STOMP dest:  │    │
│   │ (常驻右下)   │  │  确认/结果)  │  │ /user/queue/ │    │
│   │              │  │              │  │  assistant-  │    │
│   │              │  │              │  │  stream      │    │
│   └──────────────┘  └──────────────┘  └──────┬───────┘    │
│       ↑                                       │             │
│  401 触发重连 + 重订阅 (M10)                   │             │
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
| 聊天 + 工具调用 | `deepseek-ai/DeepSeek-V4-Flash` ⚠️ 需验证 | 硅基流动云端 | HTTPS (OpenAI 兼容) | 多轮对话 + 工具编排 + 摘要 |
| 文本嵌入 | `BAAI/bge-m3` | 硅基流动云端 | HTTPS (OpenAI 兼容) | RAG 文档嵌入 + 用户/设备画像 |
| 向量存储 | Chroma 1.x | 本地 Docker 容器 | HTTP (8000) | 文档 / 工单向量化检索 |

### 4.2 选型理由

- **DeepSeek-V4-Flash**:中文 SOTA,工具调用能力优于同尺寸 Qwen,Flash 档位延迟低、按 token 计费可控;比本地 Qwen2.5-1.5B/3B 强很多,工具调用稳定性大幅提升
- **BGE-M3**:中文嵌入标杆,多语种、长文本(8192 token)支持好,硅基流动托管免运维
- **Chroma**:Spring AI 官方 starter (`spring-ai-starter-vector-store-chroma`),Python 实现易运维,自包含 DuckDB+Parquet 持久化,适合论文规模(< 100k 文档)

### 4.3 ⚠️ 模型可用性预检(B1 修复)

`DeepSeek-V4-Flash` 是较新模型,部署前**必须**验证其存在于硅基流动当前 model list 中。预检命令(部署到腾讯云后第一次跑):

```bash
# 不带 key 列出公开可见性(若 siliconflow 限免需带 key)
curl -sS https://api.siliconflow.cn/v1/models \
  -H "Authorization: Bearer ${SILICONFLOW_API_KEY}" \
  | jq '.data[].id' | grep -i 'DeepSeek-V4-Flash'
```

- **若返回模型 ID** → 通过,继续
- **若不返回** → 降级到 `deepseek-ai/DeepSeek-V3.1`(在硅基流动上稳定可用)
- **若 V3.1 也不可用** → 降级到 `Qwen/Qwen2.5-14B-Instruct`

降级不需改代码,只需 `application-siliconflow.yml` 改 `model` 字段后重启。降级对论文无影响,可在实验章节诚实记录"原计划 V4-Flash,因可用性改用 V3.1"。

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
| 10 | `take_repair_ticket` | 写 | 管理员 | **必须** | `RepairReportService.take` |

### 5.3 工具元数据示例

```java
@Component
public class ReservationTool {
    private final ReservationService reservationService;

    // 注意:@PreAuthorize 写在 @Tool 方法上**无效**——Spring AI 通过反射调用,
    // 绕过了 Spring 代理。权限隔离**只**由 ToolRegistry 在 ChatClient 注入前完成
    // (参见 §6.1)。此处的方法注解仅作代码可读性提示,实际拦截靠 ToolCallback
    // 包装层(参见 §6.1.1)。

    @Tool(description = "创建一条新的设备预约,需用户确认后执行")
    @ConfirmRequired(
        reason = "将创建一条新预约,占用设备某时段",
        riskSummary = "若该时段已被人预约,创建将失败"
    )
    public ReservationVO createReservation(
        @ToolParam(description = "设备 ID,Long 类型") Long deviceId,
        @ToolParam(description = "开始时间,ISO-8601 local datetime 格式 2026-07-08T14:00:00") String startTime,
        @ToolParam(description = "结束时间,ISO-8601 local datetime 格式 2026-07-08T16:00:00") String endTime,
        @ToolParam(description = "使用目的,不超过 100 字") String purpose
    ) {
        // 调现有 service,返回 VO
        return reservationService.create(...);
    }
}
```

### 5.4 工具参数 schema(B4 修复)

每个工具必须有:JSON schema 形参、必填字段、由 LLM 还是 Java 解析、失败错误码、示例用户语。

#### 1. `search_devices(keyword, time_range, category)`
```json
{
  "type": "object",
  "properties": {
    "keyword":   {"type": "string",  "description": "设备名/型号/描述中的关键词,可空"},
    "time_range": {"type": "string",  "description": "ISO-8601 interval,如 2026-07-08T14:00/2026-07-08T18:00,可空"},
    "category":   {"type": "string",  "description": "设备类目中文名,如 '光学仪器',可空"}
  }
}
```
- 必填:**无**(全可选,LLM 可传空查询)
- 解析:Java 端 `DeviceService.searchByCriteria(keyword, startTime, endTime, category)`
- 失败码:`PARAM_INVALID`(时间格式错)/`EMPTY_RESULT`(无设备)
- 示例用户语:"周三下午能做什么" → LLM 抽出 `time_range="2026-07-08T14:00/2026-07-08T18:00"`

#### 2. `get_device_details(device_id)`
```json
{"properties": {"device_id": {"type": "integer", "description": "设备主键 ID"}}}
```
- 必填:`device_id`
- 解析:Java 端
- 失败码:`DEVICE_NOT_FOUND`
- 示例:"FACSAria 怎么样" → LLM 先 search_devices,再 get_device_details

#### 3. `get_my_reservations(status_filter)`
```json
{"properties": {"status_filter": {"type": "string", "enum": ["ALL","PENDING","APPROVED","IN_USE","COMPLETED","CANCELLED"], "default": "ALL"}}}
```
- 必填:无(默认 ALL)
- 解析:Java 端按 `SecurityContext` 当前用户过滤(学生只能看自己的)
- 失败码:无

#### 4. `recommend_devices(top_n, purpose)`
```json
{"properties": {
  "top_n":  {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
  "purpose":{"type": "string", "description": "本次使用目的,如 PCR 实验,可选,影响推荐权重"}}}
```
- 必填:无
- 解析:**调现有** `RecommendServiceImpl.recommend(userId, topN, purpose)`(亮点三复用)

#### 5. `create_reservation(device_id, start_time, end_time, purpose)` — **写工具,需确认**
```json
{"required": ["device_id", "start_time", "end_time", "purpose"], "properties": {
  "device_id":  {"type": "integer"},
  "start_time": {"type": "string", "description": "ISO-8601 local datetime,2026-07-08T14:00:00"},
  "end_time":   {"type": "string", "description": "ISO-8601 local datetime,2026-07-08T16:00:00,必须 > start_time"},
  "purpose":    {"type": "string", "maxLength": 100}}}
```
- 必填:全部
- 解析:
  - LLM 负责格式(必须是 ISO-8601 local datetime,见 §6.6 system prompt 强约束)
  - Java 端做业务校验:
    - `LocalDateTime.parse(startTime, DateTimeFormatter.ISO_LOCAL_DATE_TIME)`(失败 → `PARAM_INVALID`)
    - `SlotCalculatorService.compute(deviceId, startTime, endTime)`(必须 15 分钟对齐、startTime ≥ now、最长 720 小时)
    - `ReservationService.create` 会再次校验 + 锁防超约
- 失败码:`PARAM_INVALID` / `SLOT_NOT_ALIGNED` / `DEVICE_UNAVAILABLE` / `RESERVATION_CONFLICT` / `PURPOSE_TOO_LONG`
- 示例用户语:"约 Aria 周三 14 到 16 点做 PCR" → LLM 抽 `device_id=5, start_time=2026-07-08T14:00:00, end_time=2026-07-08T16:00:00, purpose="PCR 实验"`

#### 6. `cancel_reservation(reservation_id, reason)` — **写工具,需确认**
```json
{"required": ["reservation_id", "reason"], "properties": {
  "reservation_id": {"type": "integer"},
  "reason": {"type": "string", "maxLength": 200, "description": "取消原因,必填,记入审计"}}}
```
- 解析:Java 端 `ReservationServiceImpl.cancel` 内已有所有权校验(`r.userId == currentUserId`,管理员不受限)
- 失败码:`RESERVATION_NOT_FOUND` / `NOT_YOUR_RESERVATION`(学生越权) / `RESERVATION_STATE_INVALID`(已 IN_USE 的不能取消)

#### 7. `submit_repair_ticket(device_id, description, severity)` — **写工具,需确认**
```json
{"required": ["device_id", "description", "severity"], "properties": {
  "device_id":  {"type": "integer"},
  "description":{"type": "string", "minLength": 5, "maxLength": 500, "description": "故障描述,5-500 字"},
  "severity":   {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"], "default": "MEDIUM"}}}
```
- 解析:LLM 抽取 `severity`(枚举,默认 MEDIUM);Java 端调 `RepairReportService.create`
- 失败码:`DEVICE_NOT_FOUND` / `DESCRIPTION_TOO_SHORT`

#### 8. `search_device_manuals(query, device_id?)` — **RAG 工具**
```json
{"required": ["query"], "properties": {
  "query":      {"type": "string", "minLength": 2},
  "device_id":  {"type": "integer", "description": "可选,限定到某台设备的 SOP 文档"}}}
```
- 解析:LLM 抽 query;Java 端 `RagSearchService.search(query, deviceId, topK=5, threshold=0.6)`
- 失败码:无匹配 → 仍返回空列表,QuestionAnswerAdvisor 不报错

#### 9. `query_lab_reservations(lab_id, status, days)` — **管理员读**
```json
{"required": ["lab_id"], "properties": {
  "lab_id":  {"type": "integer"},
  "status":  {"type": "string", "enum": ["ALL","PENDING","APPROVED","IN_USE","COMPLETED","CANCELLED"], "default": "ALL"},
  "days":    {"type": "integer", "default": 7, "minimum": 1, "maximum": 90}}}
```
- 解析:`LabScopeHelper.scopeFilter(currentUser, labId)` 限定权限(管理员只能看自己实验室)
- 失败码:`LAB_NOT_FOUND` / `LAB_ACCESS_DENIED`

#### 10. `take_repair_ticket(ticket_id)` — **写工具,需确认**
```json
{"required": ["ticket_id"], "properties": {
  "ticket_id": {"type": "integer"}}}
```
- 解析:Java 端 `RepairReportService.take(id, currentUser)`,`handler_id` 自动从 SecurityContext 取(不暴露给 LLM 选,避免越权选别人)
- 失败码:`TICKET_NOT_FOUND` / `TICKET_ALREADY_TAKEN` / `TICKET_CLOSED`

### 5.5 v1 工具参数约束(flat-args only,m7 修复)

- **v1 全部用 flat positional args**,不接受嵌套 DTO
- `Long` / `Integer` / `String` / `Enum` / `List<String>` / `Boolean` 这几种基本类型
- 不传 `LocalDateTime` / `LocalDate` 等 Java 时间类型(LLM 不会调 Jackson 序列化为 java.time),改传 ISO-8601 字符串,在工具方法内 `parse`
- v2 才考虑 POJO 入参 / Jackson 嵌套 DTO / `Optional<T>`

### 5.6 ToolArgumentValidator(M7 修复)

每个工具方法调用前,Java 端跑 `ToolArgumentValidator.validate(args, schema)`:
- 必填字段缺失 → 抛 `ToolArgumentException("MISSING_FIELD:" + fieldName)`
- 枚举越界 → `INVALID_ENUM`
- 字符串长度越界 → `STRING_LENGTH_OUT_OF_RANGE`
- 时间格式错 → `PARAM_INVALID`

错误返回给 LLM 的标准 envelope:
```json
{"ok": false, "code": "PARAM_INVALID", "msg": "startTime must be ISO-8601 local datetime, got: 周三 14 点"}
```

LLM 收到后会自己纠正(在多轮对话里问用户或重新抽参),不需要前端介入。

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
                             │ (5 分钟无响应定时任务)
                             ▼
                    ┌─────────────────┐
                    │ expired         │
                    │ (自动取消)       │
                    └─────────────────┘
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

#### 错误处理(M2 修复)

- `confirmed → executing` 阶段,`ReservationService.create` 等可能抛 `BusinessException(SLOT_NOT_ALIGNED)` / `BusinessException(RESERVATION_CONFLICT)` / `BusinessException(DEVICE_UNAVAILABLE)` 等业务异常
- 异常捕获后:
  - `ai_tool_execution` 写 `status='error', error_message=ex.getCode()+':'+ex.getMessage(), executed_at=NOW()`
  - WS 推 `{type:'execution_result', action_id, result:{ok:false, code, msg}}`
  - AI 在下一轮 context 看到错误,生成自然语言回复:"抱歉,预约失败:该时段已被占用,您可以换一个时间" / "失败原因:设备当前不可用,是否换一台"
  - 写一条 `ai_message(role='assistant', tool_calls=[{status:'error', error:...}])`
  - **不自动重试**:LLM 一次性重试容易陷入循环;若需要再试,用户主动重发消息
- 用户可继续对话(状态变为 `idle` / `streaming`)

#### Pending 超时(M5 修复)

- `pending` 状态超过 **5 分钟**无响应,`AiActionTimeoutScheduler`(新增,复用现有 `LocalTimeoutScheduler` 模式)每分钟扫一次 `ai_tool_execution WHERE status='pending' AND created_at < NOW() - 5 minute`
- 自动 `pending → expired`,写 `executed_at=NOW()`,WS 推 `{type:'confirmation_expired', action_id}`
- AI 收到后向用户提示"刚才的 X 操作已超时未确认,如需要请重说一遍"

#### 抽屉关闭行为(M5 修复)

- 用户在 `awaiting_confirmation` 状态点悬浮球收起抽屉:
  - 前端弹原生 `el-dialog` 二次确认:"你有未确认的操作,确定关闭吗?"
  - 选确定 → 调 WS `{type:'cancel_action', action_id}` → 后端 `pending → cancelled` → AI 收到"用户取消了该操作"
  - 选取消 → 抽屉保持展开
- 抽屉关闭后,前端 `useAiStore` 仍记录当前 `pending` 的 `action_id`,顶栏铃铛显示红点提示用户有未处理
- 跨设备:pending 状态对 user_id 全局,任何 device 登录后都能看到(从 `ai_tool_execution` 表 query)

### 6.3 越权防护演示(m2 修复)

```
学生: "帮我接单工单 #45"
   ↓
SLM 想调 take_repair_ticket(管理员工具)
   ↓
ToolRegistry.availableFor(student) 过滤后,工具列表里没有 take_repair_ticket
   ↓
SLM 收到 tool_call error: "Tool not available"
   ↓
AI: "抱歉,接单报修工单是实验室管理员或系统管理员的权限,
     您当前是学生身份。如需报修故障设备,请说'提交报修'"
```

**两层防御**:
- **Registry 过滤(本演示)**:学生压根看不到管理员工具的描述,LLM 想调也调不出来
- **Service 层 ownership check**(已在现有代码):即使 `cancel_reservation` 学生也能调,但 `ReservationServiceImpl.cancel` 内部校验 `r.userId == currentUserId`,跨用户调用返回 `NOT_YOUR_RESERVATION`

两层叠加 = 防御纵深。Registry 防止 LLM 误用(描述都不展示),Service 防止对象级越权(工具能调但数据隔离)。

### 6.4 多轮对话与上下文管理

- **持久层**:`ai_conversation` + `ai_message` 表,按 `user_id` 索引
- **上下文窗口**:每个新消息加载最近 10 轮(20 条 message)
- **关键事实摘要**:当上下文超过 8 轮时,触发一次 LLM 摘要(单独调用,费用极低),压缩为 system message 注入
- **新对话**:前端 "新建对话" 按钮,创建新 conversation 记录
- **历史查看**:抽屉顶部 "历史记录" 按钮,弹层显示该用户 90 天内的对话列表

#### 6.4.1 上下文溢出算法(M3 修复)

伪代码(`AiAssistantService.buildPrompt`):

```
input: conversationId, currentUserMessage
output: List<Message> 给 ChatClient

# 1. 加载最近 20 条消息(10 轮)
recent = SELECT * FROM ai_message
          WHERE conversation_id = convId
          ORDER BY created_at DESC LIMIT 20

# 2. 估算 token 总数(1 token ≈ 1.5 中文字)
total = sum(m.token_count for m in recent) + estimate(currentUserMessage)

# 3. 决策
if total <= 3500:
    messages = [system] + recent[::-1] + [user]
else:
    # 4. 触发摘要(用同一个 chat 模型,新会话避免污染)
    summary = chatClient.prompt(
        "用 200 字以内总结以下对话的关键事实(设备/时间/操作):\n" +
        concat(recent[8:])  # 老的 8 轮
    ).call().content()

    # 5. 写回 ai_message(role='system', content=summary)
    INSERT INTO ai_message(role='system', content=summary) ...

    # 6. 构造新 prompt
    messages = [system, summary_msg] + recent[8:][::-1] + [user]

    # 7. 失败兜底:摘要调用失败 → 静默丢弃最早 5 轮,继续
    if summary_call_failed:
        messages = [system] + recent[10:][::-1] + [user]
        log.warn("summary failed, dropped oldest 5 turns")

# 8. token 预算分配(总 4096)
#   system prompt:  ~500 tokens
#   摘要:           ~300 tokens
#   最近窗口:       ~3000 tokens
#   user 当前:      ~300 tokens
```

**关键点**:
- 摘要 LLM 调用与正常对话用同一个 chat 模型(无需额外部署)
- 摘要成本极低(200 字生成 ≈ 0.001 元/次)
- 失败兜底是"丢消息"而不是"阻塞用户输入"

### 6.5 RAG 实现(Spring AI QuestionAnswerAdvisor)

```java
@Bean
ChatClient chatClient(ChatModel chatModel, VectorStore vectorStore) {
    return ChatClient.builder(chatModel)
        .defaultAdvisors(
            new QuestionAnswerAdvisor(vectorStore, SearchRequest.defaults()
                .withTopK(5)
                .withSimilarityThreshold(0.6))
        )
        .build();
}
```

**RAG 数据流**:
1. 用户问:"BD Aria 怎么开机?"
2. ChatClient 调用 QuestionAnswerAdvisor
3. Advisor 用 BGE-M3 把问题嵌入成 1024 维向量
4. Advisor 调 Chroma 在 `lab_manuals` 集合里检索 top-5 相似文档(余弦相似度 ≥ 0.6)
5. Advisor 把文档拼到 user message 后面(默认行为,**不是** system message,见 n4)
6. 整个 prompt 发给 DeepSeek-V4-Flash
7. LLM 基于文档生成答案

#### 6.5.1 Chroma 集合契约(M6 修复)

| 集合名 | 用途 | embedding model | dim | distance |
|---|---|---|---|---|
| `lab_manuals` | 设备 SOP 手册 / FAQ | BAAI/bge-m3 | 1024 | cosine |
| `lab_repair_tickets` | 历史报修工单(用于相似度检索) | BAAI/bge-m3 | 1024 | cosine |

**document 形状**:
```json
{
  "id": "uuid",                                 // Chroma 自动生成
  "document": "激光共聚焦开机步骤:\n1. ...",   // 文本内容(分块后)
  "metadata": {
    "doc_id": "manual-facsaria-001",             // 源文档 ID(去重用)
    "doc_type": "manual",                        // manual | faq | repair_ticket
    "device_id": 5,                              // 可选,过滤用
    "lab_id": 1,                                 // 可选
    "source_uri": "uploads/manuals/facsaria.pdf",// 原始来源
    "ingested_at": "2026-07-07T10:00:00",
    "chunk_index": 0,                            // 同一文档的第 N 块
    "chunk_total": 5                             // 该文档共 N 块
  }
}
```

**分块策略**:
- 工具类:`TokenTextSplitter(chunkSize=500, overlap=80)`(Spring AI 内置)
- 文本类:`RecursiveCharacterTextSplitter(chunkSize=800, overlap=100)`(按段落 → 句 → 字)
- 工单类:整条工单做一条 document(平均 200-300 token,无需分块)

**过滤表达式**:
```java
SearchRequest req = SearchRequest.defaults()
    .withTopK(5)
    .withSimilarityThreshold(0.6)
    .withFilterExpression(format(
        "device_id == %d AND doc_type IN ['manual', 'faq']",
        deviceId
    ));
```

**Schema 变更处理(M6 风险)**:如果将来换 embedding 模型维度(如 bge-m3 → 1024 → 1024 不变,稳),需手动 `RagIngestService.rebuild()`:
```java
public void rebuild() {
    chromaVectorStore.deleteCollection("lab_manuals");
    chromaVectorStore.createCollection("lab_manuals");
    reingestAll();
}
```

#### 6.5.2 RAG 空匹配守卫(m1 修复)

- `similarityThreshold=0.6` 过滤掉不相关文档(top-5 可能 < 5)
- 若 top-5 全低于阈值,QuestionAnswerAdvisor 不报错,只是 context 文档部分为空
- System prompt 显式约束:"若参考文档为空或与问题无关,请回答'暂无相关文档,建议联系实验室管理员',不要凭印象编造"

### 6.6 System Prompt 强约束(M7 修复)

注入到 ChatClient 的 system message(每次请求都附加,按角色不同微调):

```
你是实验室预约系统的 AI 助手,服务于 [STUDENT|LAB_ADMIN|SYS_ADMIN] 角色。

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
- 检索到文档时引用来源(如"根据《BD Aria 开机 SOP》")
- 检索不到时明确说"暂无相关文档",不要编造
```

后端代码:

```java
.systemPrompt(systemPromptBuilder.build(user.getRole()))
```

`systemPromptBuilder` 按角色模板拼接(学生 / 实验室管理员 / 系统管理员)。Student prompt 强调权限范围;管理员 prompt 强调影响范围(每次写操作都估算"将影响 N 条记录")。

---

## 7. 前端设计

### 7.1 视觉规范

- **复用 V5 深色 token**(`--accent` 青色、`--bg-surface` 等)
- 悬浮球:右下角固定,48px 圆形,`--accent` 渐变背景,带脉冲点呼吸动效
- 抽屉:右侧 380px 宽,`--bg-surface` 背景,圆角 16px
- 消息气泡:用户消息靠右 + `--accent` 渐变,AI 消息靠左 + `--bg-elevated`
- 确认卡片:`--bg-elevated` + 左侧 3px 警告色竖条 + 2 按钮(确认/取消)
- 设备列表卡片:网格布局,每项显示设备名 + 类别 + 可用时段
- **z-index 顺序(m3 修复)**:悬浮球 `z-index: 50`,抽屉 `z-index: 49`,MainLayout sticky 顶栏 `z-index: 10`,el-aside 侧栏 `z-index: 1`,抽屉在最上层

### 7.2 后续章节不变

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
# 实际密钥文件,gitignore 排除(.gitignore 已纳入)
spring:
  ai:
    openai:
      base-url: https://api.siliconflow.cn/v1
      api-key: ${SILICONFLOW_API_KEY_PLACEHOLDER}  # ⚠️ 由运维填入真实 key,不入 git
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

### 9.1 API key 处理细节(M8 修复)

- 真实 key 由用户在生产环境手工填入 `application-siliconflow.yml`,**spec 文档绝不包含明文 key**
- `.gitignore` 增量:`application-siliconflow.yml`(已规划)
- 模板文件 `application-siliconflow.yml.example` 入 git,内容是上面这份但 key 行写 `api-key: REPLACE_ME`
- logback 屏蔽:在 `logback-spring.xml` 中加 converter 防止 Authorization header 泄漏:
  ```xml
  <conversionRule conversionWord="maskedAuth"
                  converterClass="com.lab.reservation.logging.MaskedHeaderConverter"/>
  ```
  对应 Java 类用 `MessageConverter` 替换 `Bearer sk-xxx` 为 `Bearer ****`
- Spring AI ChatModel 默认会在 DEBUG 级别打印 request body,生产配置强制 `logging.level.org.springframework.ai=WARN`
- 轮换:运维改 yml + `docker compose restart backend`;**强烈建议首次部署前先 rotate 当前 key**(已在本对话中明文给出,假设为已暴露)

### 9.2 限流(M9 修复)

引入 Bucket4j(Redis-backed,项目已用 Redis):

```xml
<dependency>
    <groupId>com.bucket4j</groupId>
    <artifactId>bucket4j_jdk17-redis</artifactId>
    <version>8.10.1</version>
</dependency>
```

`AiAssistantService.sendMessage()` 入口先 `bucket.tryConsume(1)`,超限:
- WS 推 `{type:'error', code:'RATE_LIMIT', msg:'操作过于频繁,请稍后再试'}`
- 写 `ai_tool_execution` 审计行(`tool_name='_ratelimit_'`)

`application-siliconflow.yml` 配:
- `ai.assistant.ratelimit.capacity=20` 每用户桶容量
- `ai.assistant.ratelimit.refill-per-minute=20` 令牌补充速率

外加 Resilience4j `@CircuitBreaker` 保护硅基流动出口调用,失败率 50% / 10 calls → open 60s,fast-fail 返回"AI 助手暂时不可用"。

---

## 10. 数据流(端到端一条消息)

### 10.0 WebSocket 消息契约(B5 修复)

复用现有 STOMP 端点 `/api/ws`(已有 `JwtHandshakeHandler` + `WsAuthHandshakeInterceptor`),不新增端点。新增 STOMP destination prefix:`/user/queue/assistant-stream`(每个 user 私有队列),与现有 `/user/queue/notifications` 并存。

#### 客户端 → 服务端(STOMP `SEND` 到 `/app/assistant/*`)

```typescript
// frontend/src/types/ai.ts
type ClientMsg =
  | { type: 'user_message'; conv_id: number | null; text: string }
  | { type: 'confirm_action'; action_id: number }
  | { type: 'cancel_action'; action_id: number }
  | { type: 'resync'; last_seq: number };  // M4 修复,断线重传用
```

#### 服务端 → 客户端(STOMP 推送到 `/user/queue/assistant-stream`)

```typescript
type ServerMsg =
  // 流式增量(每个 chunk 一帧)
  | { type: 'delta'; seq: number; conv_id: number; text: string }
  // 整轮结束
  | { type: 'assistant_done'; seq: number; conv_id: number;
      tool_calls: Array<{name: string; args: any; result?: any; status: 'ok'|'error'}> }
  // 写工具待确认
  | { type: 'confirmation_required'; seq: number; action_id: number;
      tool_name: string; summary: string; risk: string; args: any;
      estimated_impact?: string }  // 如 "影响 1 条设备"
  // 写工具超时自动取消(M5)
  | { type: 'confirmation_expired'; action_id: number }
  // 写工具执行结果
  | { type: 'execution_result'; seq: number; action_id: number;
      result: { ok: boolean; code?: string; msg?: string; data?: any } }
  // 错误
  | { type: 'error'; code: 'RATE_LIMIT'|'AUTH_FAIL'|'INTERNAL'|'TOOL_FAIL'; msg: string }
  // 心跳(每 30s)
  | { type: 'ping'; ts: number };
```

#### 流式结束判定

- 服务端在 SLM 流结束后推一条 `assistant_done` 帧(唯一终止信号)
- 客户端在收到 `assistant_done` 前,持续 append `delta.text`
- `assistant_done.tool_calls` 列出本轮所有 tool_call(读工具结果 / 写工具待确认)
- `seq` 单调递增,跨断线重传时客户端用 `last_seq` 续传

#### 错误处理

- 服务端内部异常(LLM 4xx/5xx、Chroma 不可达、JWT 过期):
  - 推 `{type:'error', code, msg}` 一次
  - 推 `{type:'assistant_done', seq, tool_calls:[]}` 收尾
  - 客户端 `InputBar` 状态回到 `idle`
- 客户端断网:
  - `useWebSocket.ts` 自动重连(复用现有 5s 退避)
  - 重连后客户端发 `resync` 携带 `localStorage.lastSeq`
  - 服务端收到 `resync` 后,从 conversation 最近的 `seq > lastSeq` 的消息开始重推

### 10.1 正常流程(读工具)

```
[1] 用户在输入框敲字,回车
[2] useAiStore.sendMessage(text)
[3] STOMP SEND {type:'user_message', conv_id, text} → /app/assistant/send
[4] AiAssistantController 收到,验证 Principal,加载 conv 历史(滑动窗口 10 轮)
[5] ChatClient.prompt() 注入 system + history + 当前 user msg
[6] ToolRegistry.availableFor(user) 过滤出 8 个可用工具
[7] ChatClient.call() 调硅基流动 DeepSeek-V4-Flash(stream=true)
[8] SLM 流式返回 chunks,后端逐 chunk 推 WS {type:'delta', seq, text}
[9] SLM 输出 tool_call: search_devices({keyword:"流式", time_range:"周三 14-18"})
[10] 后端解析,ToolCallback 直接执行(读工具,无确认)
[11] 工具结果注入下一轮 context,继续调 SLM
[12] SLM 基于搜索结果生成自然语言回复
[13] WS 推 {type:'assistant_done', seq, tool_calls:[{name, args, result, status:'ok'}]}
[14] 前端渲染:用户消息 + AI 回复(含设备列表卡片)
```

### 10.2 写工具流程(带确认)

```
[1-8] 同 10.1
[9] SLM 输出 tool_call: create_reservation({device_id:5, start_time:"2026-07-08T14:00:00", ...})
[10] 后端解析,工具标注 @ConfirmRequired
[11] 不执行,写 ai_tool_execution(status='pending', seq=currentSeq+1)
[12] WS 推 {type:'confirmation_required', seq, action_id, tool_name, summary, args}
[13] 前端渲染确认卡片,显示设备名/时间/用途/风险说明
[14] 用户点"确认" → STOMP SEND {type:'confirm_action', action_id} → /app/assistant/confirm
[15] 后端更新 ai_tool_execution(status='confirmed', user_confirmed_at=NOW)
[16] 后端调 ReservationService.create
[17] 更新 ai_tool_execution(status='executed', result=..., executed_at=NOW)
[18] WS 推 {type:'execution_result', seq, action_id, result}
[19] AI 自动续一句"已为您预约成功,通知已发送"(再走一轮 10.1 step 7-13)
[20] 前端渲染结果卡片
```

### 10.3 WS 断线重传(M4 修复)

```
[T0] 客户端收到 seq=42 的 delta
[T1] 客户端网络断
[T2] 客户端用 useWebSocket.ts 自动重连(5s 退避,最多 3 次)
[T3] 重连成功后,客户端从 localStorage 读 lastSeq=42
[T4] STOMP SEND {type:'resync', last_seq:42} → /app/assistant/resync
[T5] 后端从 DB 读 ai_message 找到 seq=42 之后的所有 frame
[T6] 重新推送给客户端(delta / assistant_done / confirmation_required 全部 replay)
[T7] 客户端合并到当前 conversation 状态,seq 续到最新
```

**特殊情况**:用户断在 `pending → confirmed` 之间(已确认但未收到 executed),可能产生"幽灵 confirmed":
- 5 分钟后,`AiActionTimeoutScheduler` 扫到 `status='confirmed' AND confirmed_at < NOW() - 5min AND status != 'executed'`
- 自动 `status='error', error_message='TIMEOUT_NO_RESULT'`
- 写一条 `ai_message(role='system', content='上次操作超时未返回结果,请重试')`
- AI 在下一轮对话时主动告知用户

### 10.4 越权流程(m2 修复)

```
[1-6] 同上(假设学生)
[7] ToolRegistry.availableFor(student) → 6 个学生工具
[8] SLM 想调 take_repair_ticket(管理员工具)
[9] ToolCallback 抛出 ToolNotAvailableException
[10] SLM 收到工具调用错误,在下一轮生成自然语言回复
[11] WS 推 {type:'assistant_done', text:"抱歉,接单工单是管理员权限,您当前是学生身份"}
[12] 前端渲染该解释消息
```

(注:示例用 `take_repair_ticket` 而不是 `cancel_reservation_for_other_user`,因为 `cancel_reservation` 学生也能用,只是底层 service 拒绝跨用户操作——这是服务层防御,与 registry 过滤无关。registry 过滤防御的是"工具描述都不让 LLM 看到",服务层防御的是"工具能用但数据不可见"。)

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

- **用例集**:构造 30 个测试用例,按类别拆分(m6 修复):

| 类别 | 数量 | 目标准确率 | 实测 |
|---|---|---|---|
| 读工具(查设备/查预约/查统计/推荐) | 10 | ≥ 95% | |
| 写工具(创建/取消预约、提交报修) | 10 | ≥ 90%(含多轮参数修正) | |
| RAG(设备手册问答) | 5 | ≥ 85%(top-1 命中率) | |
| 越权防护(学生越权调管理工具) | 5 | = 100%(硬性,论文诚信指标) | |
| **合计** | **30** | | |

- **指标**:
  - 工具调用准确率(LLM 选对工具的比例)
  - 工具参数抽取正确率(参数与用户意图一致)
  - 端到端 **P50 / P95 / P99** 延迟(分位数,含冷启动 vs 缓存命中,见 n5)
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
    image: chromadb/chroma:1.0.0   # ⚠️ 1.x(m8 修复:0.5 与 Spring AI 2.0 starter 不兼容)
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
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v2/heartbeat"]  # n6 修复:1.x 路径
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  chroma_data:
```

### 14.1.1 JWT 刷新与长会话处理(M10 修复)

现有 JWT 有效期 7200s(2h)。WS 长会话下的过期处理:

- **前端**:`useAiStore` 监听 axios 401(任意 HTTP 调用触发),401 出现时:
  - 调 `AuthService.refresh(refreshToken)`(走 `JwtAuthController` 现有接口)
  - 拿到新 token 后:`useWebSocket.reconnect(newToken)`,WS 用新 token 重连
- **后端**:`/api/ws` 的 `JwtHandshakeHandler` 在每次重连时验证新 token,Principal 重新注册
- **断网 vs token 过期**:
  - 单纯断网 → 5s 退避重连,token 仍有效
  - token 过期 + 断网 → 客户端必须先调 `/auth/refresh` 拿到新 token 再重连
- **不主动断**:服务端不主动踢长连接(避免误伤),由客户端主动 reconnect

### 14.1.2 /api/ai/test 端点(n7 修复,冒烟测试用)

```java
@RestController
@RequestMapping("/api/ai")
public class AiTestController {
    @PostMapping("/test")
    public Result<String> test(@RequestBody AiTestRequest req,
                                @AuthenticationPrincipal SysUserDetails user) {
        // 直接调 ChatClient,跳过 WebSocket 和工具调用
        String reply = chatClient.prompt(req.getText()).call().content();
        return Result.ok(reply);
    }
}
```

冒烟测试命令(部署后第一次跑):

```bash
curl -X POST http://localhost:8080/api/ai/test \
  -H "Authorization: Bearer ${JWT}" \
  -H "Content-Type: application/json" \
  -d '{"text":"你好,你能做什么?"}'
```

期望:返回 AI 自我介绍(含工具列表摘要)。

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
| B | 工具层(10 个 @Tool + 反射注册 + 权限过滤) | **7**(n9 修复:5 天偏紧,DTO 翻译 + 验证器吃 2 天) |
| C | 确认机制 + 审计日志(状态机 + ai_tool_execution) | 3 |
| D | WebSocket 流式 + 多轮上下文(§10.0 契约 + resync) | 4 |
| E | 前端悬浮球 + 抽屉 + 卡片库(V5 深色 token) | 5 |
| F | RAG(手册 / 工单向量化 + Chroma 集合 + §6.5.1 schema) | 4 |
| G | 评估实验 + 论文章节(亮点六) | 5 |
| **合计** | | **~31 天** |

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
