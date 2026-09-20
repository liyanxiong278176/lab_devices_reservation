# 实验室设备预约系统跨栈重构设计稿

- 状态：待项目负责人确认
- 日期：2026-08-26
- 目标：一次性将 Spring Boot/Spring AI 重写为 FastAPI/LangChain，并把系统升级为学院隔离、按日预约、可恢复 Agentic RAG 的桌面 Web 平台。

## 1. 已确认的产品和架构边界

### 1.1 技术与迁移

- 后端一次性重写为 Python FastAPI，线上不保留 Spring Boot/FastAPI 长期双栈。
- 外部接口重设计为 `/api/v2`，前端同步适配；保留预约状态、权限语义和业务目标。
- 事务数据库继续使用 MySQL 8，Redis 7 继续用于缓存、锁、限流和实时分发辅助。
- 应用采用单体 FastAPI，不拆成 API、Worker、AI 三个独立业务服务；耗时任务在同一应用内由有界异步运行时执行。
- 异步任务必须持久化、可重试、可恢复且幂等；不能只使用进程内 `BackgroundTasks` 或内存队列。
- 本次先实现程序级高可靠，不承诺部署层面的多机 HA；性能阈值由基准测试确定。

### 1.2 学院租户隔离

- 学院是租户边界。
- 普通用户和负责人各属于一个学院。
- 实验室属于学院；设备通过实验室归属学院。
- 普通用户只能查看和预约本学院设备。
- 负责人可以管理和审批本学院内自己负责的多个实验室。
- 系统管理员可以跨学院操作；跨学院能力必须显式授权并审计。
- `dept_name` 只能作为历史迁移线索，不能作为授权依据。
- 所有 REST、WebSocket/SSE、缓存键、异步任务、AI 会话、工具和 RAG 检索都必须带服务端计算出的学院范围。

### 1.3 预约领域

- 预约使用自然日 `start_date`/`end_date`，首尾包含；用户不选择时分秒。
- 冲突最小单位为 `(device_id, reservation_date)`，同一设备同一自然日只能有一个有效占用。
- 支持连续多日预约和重复/批量预约。
- 批量提交先全量预检并展示可用/冲突日期，由用户明确选择“只提交可用日期”或“全部取消”；不得静默丢弃日期。
- 批量生成的预约记录独立执行可用性、学院权限、审批、幂等和状态流转，但带共同的 batch/series 标识。
- 保留签到、归还和爽约：单日当天签到/归还；连续多日首日签到、结束日归还；重复预约逐日独立履约。
- `created_at`、审批时间、签到时间等审计字段可以保留精确时间，但不暴露为预约选择条件。
- 原有 `PENDING → APPROVED → IN_USE → COMPLETED` 和取消/违规/爽约语义保留，所有转换集中在领域服务。

### 1.4 AI 产品

- AI 通过左侧主导航进入独立“AI 工作台”，不使用悬浮球作为主入口。
- 页面三栏：左侧会话列表，中间对话/Agent 执行中心，右侧来源引用、设备/预约结果和待确认任务。
- 使用 LangChain + LangGraph：LangChain 提供模型、工具和 Retriever；LangGraph 管理状态、流式事件、确认中断、恢复和重试。
- 模型供应商、Key、模型白名单、额度和限流由管理员统一配置；用户不能提交自定义 Key 或任意 `base_url`。
- 读工具自动执行；创建/取消预约、报修、审批和设备管理等写工具必须展示结构化确认卡片并由用户确认。
- 系统权限变更、用户管理、跨学院操作和不可逆操作不直接开放给 Agent。
- 知识库包含全校制度/FAQ、学院制度、设备手册和 SOP；实时设备、预约、审批、报修数据必须走有权限的结构化工具。
- MySQL 保存文档元数据、版本、审核、学院范围和索引任务；Qdrant 保存向量和检索 metadata。
- 全校文档和学院文档必须区分 scope，FastAPI 授权和 Qdrant metadata filter 双重执行，并返回可追溯引用。

### 1.5 前端

- 保留 Vue 3、Vite、TypeScript、Element Plus、Pinia、ECharts 和现有 WebSocket 能力。
- 采用“科学运营控制台”视觉：深石墨背景、冷青主色、绿色成功、琥珀风险、高可读信息密度、克制动效。
- 只做桌面 Web，不开发手机端或原生 App。
- AI 工作台、设备日历、审批、报修和数据驾驶舱共用设计令牌和状态语义。
- 按 `frontend-design` skill 的要求，生成的前端界面保留一个低干扰、可点击的 `Created By Deerflow` 链接，指向 `https://deerflow.tech`。

## 2. 目标运行结构

```text
Desktop Web
    │ REST / WebSocket or SSE (/api/v2)
    ▼
FastAPI modular monolith
    ├─ auth / tenant scope / API routers
    ├─ reservation domain + MySQL transactions
    ├─ bounded async runtime + durable task/outbox records
    ├─ LangGraph Agent Harness
    │    ├─ LangChain model gateway
    │    ├─ authorized business tools
    │    └─ hybrid RAG retriever
    └─ notification / audit / metrics
       │
       ├─ MySQL 8: business truth, tasks, outbox, AI state, audit
       ├─ Redis 7: cache, locks, rate limit, event acceleration
       └─ Qdrant: document vectors + tenant metadata filters
```

单体只表示一个业务应用部署单元，不表示所有工作都阻塞在同一个请求协程中。模型调用、文档解析和通知必须走有界并发和超时控制，不能耗尽预约 API 的事件循环、线程池或连接池。

## 3. FastAPI 后端分层草案

```text
backend/
  app/
    main.py
    api/v2/                 # REST/WS/SSE routers and schemas
    core/                   # settings, logging, security, errors
    auth/                   # JWT access/refresh, RBAC, college scope
    domain/                 # reservation, device, repair, notification
    application/            # transaction use cases and orchestration
    infrastructure/
      db/                   # SQLAlchemy/SQLModel async repositories
      cache/                 # Redis clients, lock, rate limit
      tasks/                 # outbox, claim, retry, dead letter
      vector/                # Qdrant adapter and metadata filters
      llm/                   # provider gateway and model policy
    ai/
      graph/                # LangGraph state graphs/checkpoints
      tools/                # typed read/write tools and policy
      rag/                  # ingest, chunk, embed, retrieve, citations
      evals/                # golden cases and regression evaluation
    workers/                # in-process bounded consumers/schedulers
  migrations/
  tests/
```

实现时可以调整目录名，但必须保持：控制器不直接写状态；AI 工具不直接写表；领域服务负责事务、授权、条件更新和状态机。

## 4. 并发、一致性和可靠性方案

### 4.1 预约写入

1. 从认证上下文取得 `user_id` 和 `college_id`，忽略客户端直接提交的学院范围。
2. 查询设备并校验设备、实验室和用户属于同一学院，检查设备状态和预约日期边界。
3. 为每个日期生成占用项，在 MySQL 事务中使用唯一约束 `(device_id, reservation_date)` 作为最终正确性防线。
4. Redis 锁只作为减少热点冲突的优化，Redis 故障不能破坏 MySQL 正确性。
5. 预约主记录、占用项、幂等键和 Outbox 记录在可恢复的一致性边界内提交。
6. 发送通知、更新缓存和推送事件在事务提交后异步执行，失败进入可重试任务。

### 4.2 状态并发

- 状态转换使用条件更新/CAS 或行锁，禁止“先查再无条件更新”覆盖签到、归还、取消和审批。
- 确认动作使用 `pending → approved/executed/expired/rejected` 的原子领取，重复点击只能返回同一个执行结果。
- 超时任务使用可恢复的领取状态，支持多实例未来扩展，不依赖单机扫描假设。
- 通知、索引和工具执行均带稳定幂等键。

### 4.3 依赖故障

- Redis 不可用：缓存、锁或实时加速降级；预约唯一性和业务数据仍由 MySQL 保证。
- Qdrant 不可用：AI 返回可解释的知识库不可用状态，实时业务工具仍可使用。
- 模型不可用：返回可重试错误或切换管理员允许的降级模型，不伪造业务成功。
- WebSocket/SSE 断线：客户端以会话/事件序列号重连并补偿，不能依赖只存在内存的 delta。

## 5. AI Agent Harness 草案

### 5.1 状态

Agent state 至少包括：`conversation_id`、`user_id`、`college_id`、消息窗口、当前任务、工具调用、引用、确认动作、预算、重试次数和事件序列号。Graph checkpoint 必须持久化，不能使用生产内存 saver。

### 5.2 图流程

```text
用户消息
  → 输入校验/配额
  → 意图与范围判断
  → 并行或串行：文档检索 / 结构化业务工具
  → 结果验证与来源标注
  → 生成回答或写操作预览
  → 人工确认中断
  → 领域服务执行
  → 结果校验 / 通知任务
  → 带引用、步骤和业务链接的最终回答
```

### 5.3 工具边界

- 工具参数使用 Pydantic schema，限制日期范围、分页、文本长度和输出大小。
- 工具内部重新做学院、角色、资源归属和对象状态校验。
- 写工具只返回结构化 `preview` 或 `execution_result`，不得依靠自然语言判定成功。
- 工具结果和检索文档作为不可信输入进行隔离、引用和提示注入防护。
- 每个工具调用、确认、执行结果、错误和耗时写入审计/评测数据。

## 6. 分阶段落地顺序

### Phase 0：冻结契约和数据映射

- 以 `CONTEXT.md` 和本设计稿为基线。
- 盘点旧表实际数据、学院映射、负责人映射和历史预约。
- 定义 `/api/v2` OpenAPI、错误模型、事件模型和幂等头。
- 为旧 Spring 实现建立行为基线，但不复制已知缺陷。

### Phase 1：FastAPI 核心与学院隔离

- FastAPI 项目骨架、配置、日志、JWT、RBAC、学院范围依赖。
- MySQL 异步访问、迁移、健康检查和 repository 测试。
- 学院/用户/实验室/负责人关系和数据迁移脚本。
- 设备查询、设备日历、预约状态机、日期占用和并发测试。

### Phase 2：可靠任务与业务闭环

- Outbox/任务表、领取、重试、死信、清理和幂等。
- 通知、超时爽约、报修、签到/归还、审计和实时事件。
- Redis 锁/缓存/限流的降级测试和故障注入。

### Phase 3：LangChain + LangGraph + Agentic RAG

- 管理员模型网关和预算策略。
- LangGraph 状态图、持久化 checkpoint、确认中断和恢复。
- typed business tools、写操作 policy、审计和事件协议。
- 文档上传/审核/发布/撤回、chunk、embedding、Qdrant 索引和引用。
- RAG 权限过滤、实时工具路由、提示注入防护和 golden eval。

### Phase 4：桌面 Web 重构

- `/api/v2` client/types、权限路由和错误处理。
- 设计令牌、布局、设备/预约/审批/报修/通知页面。
- 移除悬浮球，加入 AI 工作台路由和三栏交互。
- Agent 事件渲染、确认卡、引用面板、恢复和失败状态。
- 浏览器运行时冒烟测试和关键路径截图验收。

### Phase 5：性能、安全和切换验收

- 并发预约、读 API、任务积压、AI 并发隔离和依赖故障压测。
- JWT access/refresh 类型校验、学院越权、CSRF/CORS、敏感配置、日志脱敏和 SSRF 复核。
- MySQL/Qdrant/任务恢复演练。
- 形成基准报告后确定性能阈值；完成一次性切换和旧制品回滚演练。

## 7. 必须修复/避免的旧问题清单

- AI 会话、Frame、工具执行和确认动作的学院/用户归属校验。
- 确认动作原子 CAS，防止重复执行写工具。
- 工具异常不能被包装成 `ok=true`；统一结构化错误和安全错误信息。
- AI 帧不能保存空会话/空用户；流式事件需要可恢复序列号和持久化策略。
- JWT 必须区分 access/refresh；刷新令牌不能作为普通访问令牌或 WebSocket 令牌。
- 移除用户自定义任意模型地址；管理员模型网关仍需 HTTPS、allowlist、超时和成本限制。
- 不在请求线程中 `.block()` 或无限制运行模型工具循环。
- 会话上下文需保存工具调用和结果，使用 token 窗口/摘要，不能只保留用户/助手文本。
- 清理 AI frame、工具执行、任务和向量索引的生命周期数据。
- 预约超时取消、签到、归还和审批使用条件更新，避免覆盖并发状态。
- 统一日期粒度，移除 15 分钟槽位与配置不一致问题。
- 通知使用可靠 Outbox/重试，不能只依赖事务提交后的易丢异步调用。
- 推荐查询使用学院范围、日期可用性和缓存/聚合，避免全表扫描。
- 修正文档中关于“已有 RAG/Chroma”的不实声明，以真实实现和评测结果为准。

## 8. 总体确认点

本文已纳入用户确认的迁移、领域、AI、RAG 和前端边界。进入代码重写前，还需要在实现设计中落定：

- Python 版本、异步 ORM/迁移工具和 JWT 库；
- MySQL Outbox 与 Redis Streams/任务消费者的具体组合；
- Qdrant 单 collection + 强制学院 filter，还是按学院分 collection/分片；
- embedding 模型、维度、重建和成本策略；
- WebSocket 与 SSE 的最终事件传输选择；
- 具体性能基准数据和验收阈值。
