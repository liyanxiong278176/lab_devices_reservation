# LabFlow 实验室设备预约系统

当前运行时采用单体异步架构：

- `backend/`：Python 3.13 + FastAPI + SQLAlchemy Async + Alembic，统一 API 前缀为 `/api/v2`。
- `frontend/`：Vue 3 + Vite + TypeScript，桌面 Web 优先；AI 入口位于左侧“AI 工作台”。
- MySQL 8：业务数据、学院租户、自然日预约占用、幂等键与 durable outbox。
- Redis 7：预约锁、租户目录缓存、Lua 限流和推荐缓存；设置短超时与进程级熔断，故障时由数据库唯一约束、缓存回源和进程内限流兜底。
- Qdrant：学院/全局知识库向量检索；MySQL 保存文档元数据、版本和权限事实。

本轮非 AI 可靠性改造还包括：按“设备 + 自然日”排序加锁与数据库唯一约束双重防超约；设备目录使用学院租户隔离的 Cache-Aside、TTL 抖动和热点保护；Redis Lua 令牌桶限流并在 Redis 故障时降级到进程内限流；MySQL Outbox 采用租约领取、聚合键串行、指数退避、死信和管理员重试；高增长列表支持 `cursor` 主键游标分页；`/api/v2/metrics` 提供进程级指标，`/api/v2/ready` 区分数据库故障与 Redis 降级。

## 本地验证

```powershell
docker compose up -d mysql redis qdrant
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

cd ..\frontend
pnpm install
pnpm dev
```

后端检查：

```powershell
cd backend
uv run ruff check .
uv run pytest -q
```

预约并发黑盒验证：

```powershell
cd backend
uv run python benchmarks/reservation_concurrency.py --base-url http://127.0.0.1:8000/api/v2 --token <ACCESS_TOKEN> --device-id <DEVICE_ID> --date 2099-01-01 --clients 100
```

同一设备同一天的并发请求应恰好 1 个返回 201，其余返回 409；压测数据请使用专用未来日期并在测试后清理。

首次初始化时可在 `.env` 设置 `LAB_BOOTSTRAP_ADMIN_PASSWORD`，服务只会在账号不存在时创建全局 `admin` 管理员，不会覆盖已有账号。

`src/` 与 `pom.xml` 保留为旧 Spring Boot 参考源码；容器、开发文档和实际运行入口均以 `backend/` 为准。设计决策与迁移说明见 [`CONTEXT.md`](CONTEXT.md) 和 [`docs/superpowers/specs/2026-08-26-fastapi-langchain-rebuild-design.md`](docs/superpowers/specs/2026-08-26-fastapi-langchain-rebuild-design.md)。
