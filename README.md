# LabFlow 实验室设备预约系统

当前运行时采用单体异步架构：

- `backend/`：Python 3.13 + FastAPI + SQLAlchemy Async + Alembic，统一 API 前缀为 `/api/v2`。
- `frontend/`：Vue 3 + Vite + TypeScript，桌面 Web 优先；AI 入口位于左侧“AI 工作台”。
- MySQL 8：业务数据、学院租户、自然日预约占用、幂等键与 durable outbox。
- Redis 7：预约锁、租户目录缓存、Lua 限流和推荐缓存；设置短超时与进程级熔断，故障时由数据库唯一约束、缓存回源和进程内限流兜底。
- Qdrant：学院/全局知识库向量检索；MySQL 保存文档元数据、版本和权限事实。

本轮非 AI 可靠性改造还包括：按“设备 + 自然日”排序加锁与数据库唯一约束双重防超约；设备目录使用学院租户隔离的 Cache-Aside、TTL 抖动和热点保护；Redis Lua 令牌桶限流并在 Redis 故障时降级到进程内限流；MySQL Outbox 采用租约领取、聚合键串行、指数退避、死信和管理员重试；预约、审批、报修、通知、设备、用户和实验室列表使用 ID 子查询延迟关联，支持页码直跳并限制最多跳过 100,000 条匹配记录；履约采用预约记录、照片和现场交接，不使用二维码；归还验收、信用事件、候补、不可预约日和完成后评价形成业务闭环。运维端点默认不向匿名用户暴露诊断信息：`/ready` 需系统管理员，`/metrics` 默认关闭并支持独立抓取密钥。

## 本地数据库凭据

首次启动前将根目录 `.env.example` 复制为 `.env`，为 `DB_ROOT_PASSWORD` 和 `DB_APP_PASSWORD` 分别填写独立的 64 位十六进制随机值；后端 `.env` 中的 `LAB_MYSQL_DSN` 应使用 `lab_runtime` 应用账号。开发 Compose 只将 MySQL/Redis 端口绑定到 `127.0.0.1`，应用账号只获 `lab_reservation` 数据库权限。已有 MySQL 数据卷不会因改 Compose 环境变量而自动创建/轮换账号；迁移已有部署时，保留当前 root 密码作为 `DB_ROOT_PASSWORD`，先在 MySQL 中创建 `lab_runtime` 并授予该数据库权限，再切换后端 DSN。不要删除数据卷。

## 本地验证

```powershell
# 初次运行前复制根目录凭据模板并填写随机密钥。
# Copy-Item .env.example .env
docker compose up -d mysql redis qdrant
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

cd ..\frontend
pnpm install
pnpm dev
```

运维端点：`/api/v2/live` 仅返回存活状态；`/api/v2/ready` 仅系统管理员可读；`/api/v2/metrics` 默认关闭，配置 `LAB_METRICS_TOKEN` 后仅接受对应 Bearer 密钥。生产 Nginx 不向浏览器代理 `/ready` 和 `/metrics`。

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

AI 服务配置从 `backend/.env` 读取，不保存在数据库；复制 [`backend/.env.example`](backend/.env.example) 为 `backend/.env`，填写 `LAB_AI_API_KEY`、`LAB_AI_EMBEDDING_API_KEY` 和 `LAB_AI_MINERU_API_KEY` 后重启后端。生产 compose 也会将该文件注入后端容器。不要提交 `backend/.env`。

本地空库恢复开发演示数据（先执行迁移；仅限非生产环境）：

```powershell
cd backend
$env:LAB_BOOTSTRAP_ADMIN_PASSWORD = '<管理员密码>'
$env:LAB_DEMO_USER_PASSWORD = '<普通用户密码>'
$env:LAB_DEMO_MANAGER_PASSWORD = '<负责人密码>'
uv run python scripts/seed_demo_data.py
```

脚本会补齐三个学院、各自的负责人/实验室/示例设备、`zhangsan` 普通用户和设备 SOP/安全须知；已存在记录不会重复创建。不要在生产环境运行演示数据脚本。

项目只保留 FastAPI/Python 后端实现，容器、开发文档和实际运行入口均以 `backend/` 为准。设计决策与迁移说明见 [`CONTEXT.md`](CONTEXT.md) 和 [`docs/superpowers/specs/2026-08-26-fastapi-langchain-rebuild-design.md`](docs/superpowers/specs/2026-08-26-fastapi-langchain-rebuild-design.md)。
