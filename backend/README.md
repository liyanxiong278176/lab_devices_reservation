# FastAPI backend

这是项目唯一运行时后端：FastAPI + SQLAlchemy async + Alembic。API 统一使用 `/api/v2`。

## 本地运行

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

首次初始化可在 `.env` 临时设置 `LAB_BOOTSTRAP_ADMIN_PASSWORD`（至少 8 位）；服务只在该账号不存在时创建 `admin` 系统管理员，不会覆盖已有账号。初始化完成后建议移除该变量。

健康检查：

- `GET http://localhost:8000/api/v2/live`
- `GET http://localhost:8000/api/v2/ready`

## 验证

```powershell
cd backend
uv run pytest
uv run ruff check .
```

核心能力包括：学院租户隔离、自然日预约与批量预检、数据库唯一键 + Redis best-effort 锁、幂等键、可恢复 outbox、报修/审批/仪表盘，以及 LangChain + LangGraph Agent Harness + Qdrant Agentic RAG。

并发验收脚本见 `benchmarks/reservation_concurrency.py`；同一设备同一天的并发请求必须只有一个 `201`，其余返回结构化 `409`。
