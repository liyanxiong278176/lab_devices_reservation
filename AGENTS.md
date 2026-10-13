# AGENTS.md

本文记录当前仓库的实现约束和 Agent 工作说明。项目运行面为Java 21/Spring Boot/MyBatis 后端与 Vue/TypeScript 前端；根目录 `README.md`、`backend-java/README.md` 和 `CONTEXT.md` 分别补充运行操作与设计背景，修改代码前应以实际运行入口和迁移为准。

## 项目结构

```text
backend-java/src/main/java/edu/labflow/ Java HTTP API、应用服务、认证、Outbox、名额对账与 SSE
backend-java/src/main/resources/db/migration/ 追加式 Flyway SQL 迁移
backend-java/src/test/             Java 单元和真实服务集成测试
backend/migrations/                原 Alembic 历史，不改已执行 revision
backend/app/、backend/scripts/      可选 SQL/Redis 数据工具，不是 HTTP 后端
backend/benchmarks/                HTTP/SQL 容量验证工具
frontend/src/                      Vue 3、TypeScript、Pinia、Element Plus
frontend/e2e/                      标准 Playwright 浏览器验收
monitoring/                        Prometheus、Grafana 和 exporter
```

`backend-java/` 是唯一后端构建入口。根目录忽略的 `target/` 是旧 Maven 产物，不作为实现依据；个人旧 Java 配置不属于项目配置，不得提交凭据。

本工作区另外存在未跟踪的 `qa_joint/` 联调脚本、截图和人工复看指南；它是本地专项验收资料，不是所有 checkout 都有的项目入口。需要使用时先读其 `README.md`。版本控制中的标准浏览器测试仍以 `frontend/e2e/` 为准。

## 本地开发命令

在仓库根目录首次配置唯一的环境配置文件：

```powershell
Copy-Item .env.example .env
```

按模板填写 MySQL、Redis、JWT 和监控配置，已有 `.env` 保留。启动：

```powershell
docker compose up -d mysql redis
cd backend-java
.\mvnw.cmd package
java -jar target/labflow-backend-1.0.0.jar
```

新库先执行 `--spring.main.web-application-type=none --labflow.migration=migrate`；已有库按 `docs/springboot-cutover.md` 显式核验、baseline 和迁移。默认不自动 baseline。Java API 内运行 Outbox、名额对账及通知 Streams 消费，不再启动 Python/Celery。

在 `frontend/` 启动和检查前端：

```powershell
pnpm install
pnpm dev
pnpm build
pnpm test
pnpm test:e2e
```

需要可见截图及普通用户/管理员人工复看时，如果工作区提供 `qa_joint/README.md`，可使用其页面复看指南；其中旧 FastAPI 启动命令已失效，应使用 Java + Vue + MySQL + Redis和 `qa_joint/scripts/`；不要把仓库中的历史手工 runner 当成当前标准 E2E 命令。

## 当前架构约束

- Spring Boot 是唯一后端 HTTP 运行面，使用 MyBatis 与 Spring 事务、Flyway；不引入 RabbitMQ。接口统一挂载在 `/api/v2`。
- MySQL 8 是预约、权限版本、通知历史、幂等结果和持久化任务的事实来源。Redis 7 用于登录会话、权限快照/业务缓存、限流、预约竞争优化、设备日名额 Hash 预占和实时事件传递。
- Redis 会话不可用时认证必须失败关闭；不能用 MySQL 伪造或恢复 Redis 会话。权限快照、目录缓存、限流和预约优化按各自实现降级。预约 Redis 锁或名额缓存不可用/未就绪时应回到 MySQL，数据库唯一约束才是最终防超约保障。
- 设备资源池可代表多台实物设备。用户预约粒度仍为自然日，使用 `start_date`、`end_date` 且首尾包含；`v2_reservation_day` 上 `(device_id, date)` 唯一约束是单设备单日的最终冲突防线。Redis 名额快照按资源池与日期加速预占，并由 MySQL 对账恢复。不要重新引入分钟槽位或时分秒输入。
- 预约状态只能由应用服务集中流转。主履约链为 `PENDING → APPROVED → IN_USE → COMPLETED`；驳回为独立 `REJECTED` 终态。取消、违规、爽约等分支必须遵守领域规则和现有条件更新，不得在 API handler 或任务中绕开状态机直接改状态。
- 签到只允许预约首日，归还只允许预约结束日；精确时间只作内部审计，不作为预约粒度。归还要记录验收；损坏/缺失要进入维护流程。维修、报废设备不可预约，设备状态变化要记录操作人、原/新状态和原因。
- 学院是租户边界。普通用户只能访问和预约本学院数据；负责人只能管理其负责的实验室/学院；系统管理员才可跨学院。所有写接口都要服务端校验租户范围，不依赖前端隐藏菜单。
- 列表深页使用延迟关联：先在 ID 子查询中完成权限过滤、筛选、稳定排序和分页，再加载本页完整记录。最多跳过 100,000 条匹配记录；前端限制可访问页并提示缩小筛选。不得先取全量实体再 OFFSET，也不得把租户过滤放在 ID 分页之后。
- MySQL Outbox 是业务后台任务的持久化来源，Java Worker 保留租约、`SKIP LOCKED`、到期任务聚合顺序、退避重试和死信/人工恢复。未来定时任务不能阻塞当前到期任务；不要改成其他队列事实源。
- 通知记录存于 MySQL。Redis Streams 使用独立消费组把完整通知事件分发到各 API 进程的本地 SSE Hub；浏览器使用同一个 EventSource 通过 `Last-Event-ID` 重连，按用户递增序号从 MySQL 补齐，单次 SSE 重放上限为 100 条，超出部分由历史/未读 HTTP 接口补偿。Redis Streams 是实时分发队列，不是通知历史事实源；当前实现不使用 Pub/Sub 作为通知主通道。
- AI、知识库、模型配置、Qdrant 与 Celery 链路已移除；仅删除 AI 专属记录，AI 曾创建的预约、报修和共享业务附件必须保留。

## 认证、授权和配置安全

- 浏览器使用 HttpOnly Cookie 承载短时 JWT。JWT 只含 `sid/type/jti/iss/aud/iat/exp`，不放身份、角色或权限。SID 使用 `secrets.token_urlsafe(32)`；登录会话和轮换后的 Refresh Token 状态保存在 Redis。
- 每个请求从 MySQL 读取账号启用状态、当前学院和全局授权版本；角色/权限快照以 `sid + authz_version` 缓存，角色分配或权限修改必须递增授权版本。账号禁用、换学院、撤权后不能继续信任旧快照。
- Refresh Token 必须轮换且可撤销；写请求须校验可信 Origin 和双提交 CSRF Token。
- 生产环境禁止默认数据库密码、默认 JWT secret 或占位凭据；必要配置缺失时应启动失败。不要读取或提交根目录忽略的旧 Java 配置来填充 Java 设置。

## 可靠性与迁移

- 状态写入用条件更新并检查影响行数，避免重复审批、签到、归还或后台任务覆盖新状态。
- Outbox 使用唯一任务键实现幂等；过期租约可恢复，重试有边界和退避，死信需要可观察/可人工恢复。重复消费不能重复执行业务变更或重复通知。
- 同一设备同一自然日的并发预约只能有一条占用成功，其余明确返回 HTTP 409。Redis 锁只减少数据库竞争，不能代替 MySQL 唯一约束。
- 后续新增或改表只能追加 Flyway migration，禁止修改已执行迁移。历史 Alembic head 为 `0038_penalties_overdue`；已有库显式核验并 baseline 1 后再迁移。必须在 MySQL 8 验证升级、约束、索引和数据兼容，禁止自动 baseline 或清库。

## 验证要求

- 后端常规检查：在 `backend-java/` 执行 `.\mvnw.cmd verify` 和 `spotless:check`；并发、MySQL 唯一约束、Redis 故障与对账、Outbox 抢占和 Streams 使用真实服务验证。先确认 DSN 指向隔离测试库。可选 Python 数据工具使用 `uv run ruff check app scripts`。
- 前端常规检查：`pnpm build`、`pnpm test`；Playwright 通过 `pnpm test:e2e` 运行 `frontend/e2e/`。真实多角色和截图联调按本地存在时的 `qa_joint/README.md` 操作。
- 浏览器 E2E 应使用真实页面验证普通用户、负责人和系统管理员的预约/审批/履约、报修、通知、权限菜单和学院隔离。并发测试应验证同设备同自然日只能一个成功。
