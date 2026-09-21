# 实验室设备预约系统：并发与分页验证

当前运行时只有 Python FastAPI + Vue，接口统一为 `/api/v2`。并发验证应直接针对自然日
预约接口。

## 本地前置

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

需要 MySQL 8 和 Redis 7。Redis 只负责降低预约竞争和提供缓存，设备日期明细表的
唯一约束 `uk_device_date_v2(device_id, date)` 才是防超约的最终事实来源。

## 并发场景

同一设备、同一天发送 50 个带不同 `Idempotency-Key` 的 `POST /api/v2/reservations`：

- 只有一个请求可以写入该设备日期；
- 其他请求返回 HTTP 409 `RESERVATION_CONFLICT`；
- Redis 正常时先使用日期锁降低数据库竞争；Redis 不可用时自动走数据库唯一约束；
- 请求使用 `start_date` / `end_date`，不再传小时、分钟或时段槽位。

示例请求：

```json
{
  "device_id": 1,
  "start_date": "2026-12-10",
  "end_date": "2026-12-10",
  "purpose": "并发一致性测试"
}
```

## 游标分页场景

列表接口第一页返回 `next_cursor`，下一页携带该值，查询等价于：

```sql
WHERE id < :next_cursor
ORDER BY id DESC
LIMIT :size
```

已接入预约、审批、报修、通知、设备和用户列表。页面仍保留页码外观，但不会对深页
继续使用大 OFFSET；筛选条件或页大小变化时，前端会清空游标链并从第一页重新开始。

## 运行检查

```powershell
cd backend
uv run pytest -q
uv run ruff check .
cd ../frontend
pnpm test
pnpm build
```

无法连接 MySQL/Redis 时，单元测试仍可使用 SQLite 验证业务逻辑；生产上线前必须额外
在真实 MySQL/Redis 环境执行并发 IT 和迁移演练。
