# 项目协作说明

请以根目录 `AGENTS.md` 和 `CONTEXT.md` 为准。

- 后端唯一运行时：Python 3.13 + FastAPI + SQLAlchemy Async + Alembic。
- API 前缀：`/api/v2`；前端是 Vue 3 + TypeScript + Pinia + Element Plus。
- 预约按自然日，不使用分钟槽位；学院是权限和数据隔离边界。
- AI 功能本轮保持现状，非 AI 业务的修改不能绕过 AI 共享的认证和租户约束。
- 修改后至少执行 `cd backend; uv run ruff check .; uv run pytest -q` 和 `cd frontend; pnpm build`。
