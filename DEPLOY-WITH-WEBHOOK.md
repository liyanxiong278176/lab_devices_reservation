# FastAPI 单体服务部署说明

当前项目只支持 Python FastAPI + Vue/Nginx 运行方式。Java、Maven、Spring Boot、RabbitMQ 和旧 `/api` 接口不属于部署内容。

## 服务组成

生产 Compose 使用 `docker-compose.prod.yml`，包含：

- `mysql`：MySQL 8 业务事实库。
- `redis`：缓存、辅助锁、限流和实时分发。
- `qdrant`：AI 知识库向量存储，本轮不修改 AI 业务。
- `app`：FastAPI `/api/v2`，进程内运行 OutboxWorker 和通知 WebSocket。
- `frontend`：Vue 构建产物和 Nginx，反代 REST、SSE 与 `/api/v2/ws`。

## 启动

在项目根目录创建 `.env`，至少设置：

```dotenv
DB_PASSWORD=replace-with-a-strong-password
JWT_SECRET=replace-with-a-random-secret-at-least-32-characters
```

生产配置不再提供数据库密码和 JWT secret 默认值。然后执行：

```powershell
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

健康检查：

```powershell
curl http://127.0.0.1/api/v2/live
curl http://127.0.0.1/api/v2/ready
```

`/ready` 会检查 MySQL；Redis 故障会标记为 degraded，因为预约正确性由 MySQL 唯一约束兜底。

## 发布要求

1. 先执行 `cd backend; uv run ruff check .; uv run pytest -q`。
2. 再执行 `cd frontend; pnpm build; pnpm test`。
3. 使用 MySQL/Redis 环境执行 Alembic migration 和并发预约验收。
4. 检查 Outbox 失败任务、通知未读数、WebSocket 重连和跨学院权限。
5. 备份数据库后再执行 `docker compose ... up -d --build`。

项目级高可用目标是程序级幂等、条件更新、Outbox 恢复、Redis 降级和数据库唯一约束；部署拓扑扩展不属于当前改造范围。
