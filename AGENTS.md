# AGENTS.md

这是高校实验室设备预约系统的唯一项目说明。项目只保留 Python 后端和
Vue/TypeScript 前端；后端运行时为 FastAPI，旧 Java 实现已经移除。

## 目录与命令

```
backend/                 FastAPI + SQLAlchemy Async + Alembic
backend/app/api/v2       REST API，统一前缀 /api/v2
backend/app/application  预约、报修、目录等应用服务
backend/app/domain       领域状态机与不变量
backend/app/infrastructure 数据库、Redis、Outbox、实时通知
backend/migrations       Alembic 迁移，只能追加新版本
backend/tests            Python 单元/接口/集成测试
frontend/src             Vue 3 + TypeScript + Pinia + Element Plus
frontend/e2e             Playwright 浏览器链路测试
```

```powershell
# 启动开发依赖
# 首次运行前复制 .env.example 为 .env，并填写 DB_ROOT_PASSWORD、DB_APP_PASSWORD。
# Copy-Item .env.example .env
docker compose up -d mysql redis qdrant

# 后端
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --loop app.core.uvicorn_loop:platform_loop_factory --reload --port 8000

# 后端检查
uv run ruff check .
uv run pytest -q

# 前端
cd ..\frontend
pnpm install
pnpm dev
pnpm build
pnpm test
```

## 架构决策

- FastAPI 是唯一后端运行面；不要新增 Java、Spring Boot、MyBatis、Flyway 或 RabbitMQ。
- 单体服务内使用异步 I/O。通知、超时、缓存失效和候补递补走持久化 Outbox，必须可恢复、可重试、幂等。
- MySQL 8 是业务与授权版本事实源；Redis 保存登录会话及短期权限快照，并负责缓存、辅助锁、限流和低延迟实时分发。Redis 故障不能破坏预约正确性，但 Redis 会话不可用时认证必须失败关闭。
- 学院是租户边界。普通用户只能访问和预约本学院设备；负责人只能管理和审批自己负责的实验室/学院；系统管理员才可跨学院。
- 预约只按自然日：`start_date`、`end_date` 首尾包含；冲突最小单位是 `(device_id, reservation_date)`。禁止重新引入分钟槽位或时分秒预约输入。
- 预约状态只能由应用服务集中流转：`PENDING → APPROVED → IN_USE → COMPLETED`；待审批/已批准且尚未开始可取消；批准/使用中可违规；批准后可爽约；驳回使用独立的 `REJECTED` 终态。
- 签到只允许预约首日，归还只允许预约结束日；内部可保存精确审计时间，但不作为用户预约粒度。
- 同一设备同一天由数据库唯一约束最终防超约，Redis 锁只做减少冲突的优化；锁失败必须回到数据库约束路径。
- 列表支持直接页码跳转，使用延迟关联：先按稳定主键 `ORDER BY id DESC` 在 ID 查询中分页，再关联读取本页完整记录；后端最多允许跳过 100,000 条匹配记录，前端限制可访问页并提示缩小筛选。学院/负责人权限过滤必须在 ID 子查询中执行，不能先取全行再 OFFSET。
- 所有写接口都要做服务端学院范围校验，不能依赖前端隐藏菜单。
- 新增或改表只能追加 Alembic revision，禁止修改已经执行过的 migration 文件。
- AI 目录、LangChain、LangGraph、Qdrant 属于独立业务边界。本轮非 AI 改造不得修改 AI Agent、RAG、模型配置或确认协议。

## 可靠性要求

- 状态写入使用条件更新并检查影响行数，防止重复审批、重复签到、重复归还和超时任务覆盖。
- Outbox 任务使用租约、`SKIP LOCKED`、指数退避、死信和唯一任务键；重复消费不能产生重复通知或重复业务变更。
- 通知表是历史事实源；SSE 只做单向实时推送，按用户严格递增序号处理同一 EventSource 的 `Last-Event-ID` 重连，最多补发 100 条，更多通过 HTTP 历史/未读接口补偿；Redis Pub/Sub 只作唤醒提示。
- 生产环境禁止使用默认数据库密码、默认 JWT secret 或默认 AI 凭据；配置缺失时启动失败。
- 浏览器使用 HttpOnly Cookie 承载短时 JWT；JWT 仅含 `sid/type/jti/iss/aud/iat/exp`，身份、角色和权限不放入 JWT。SID 使用 `secrets.token_urlsafe(32)` 生成，登录会话和轮换后的 Refresh Token 状态保存在 Redis。
- 每个请求从 MySQL 读取账号启用状态、当前学院和全局授权版本；角色/权限快照按 `sid + authz_version` 缓存在 Redis，缓存失效或不可用时从 MySQL 关系回源。角色分配或权限修改必须递增授权版本。
- Token 刷新必须轮换并可撤销；写请求必须通过可信 Origin 与双提交 CSRF 校验；用户禁用、换学院或撤权后，服务端依赖应重新读取当前用户状态。
- 所有设备状态变更要记录操作人、原状态、新状态和原因；维修、报废设备不能被预约。
- 报修完成前必须先受理；归还要保存验收结果，损坏/缺失自动进入维护状态。

## 数据库迁移

当前 Alembic head 为 `0034_notification_sequence`。新增表或索引时：

1. 新建 `backend/migrations/versions/00xx_*.py`。
2. 更新 ORM 模型和测试夹具。
3. 在 MySQL 上执行 `uv run alembic upgrade head`。
4. 验证回滚、唯一约束、索引和历史数据兼容性。

## 测试要求

- 单元测试覆盖状态机、日期边界、学院隔离和输入校验。
- SQLite 测试只能验证业务分支；并发、唯一约束、Redis 降级和 Outbox 抢占必须补 MySQL/Redis 集成测试。
- 预约并发验收：同设备同自然日并发请求只能成功一个，其余明确返回 409。
- 前端 E2E 必须以真实页面验证普通用户和管理员的预约、审批、签到、归还、报修、通知和菜单隔离。
- AI 测试不属于本轮改造范围，除非修改了共享认证或数据模型导致兼容性回归。
