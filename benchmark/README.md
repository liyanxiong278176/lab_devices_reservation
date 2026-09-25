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

## 深页随机跳转场景

列表接口使用延迟关联支持页码直跳。先只读取主键并应用排序/筛选/分页，再按本页 ID 加载实体，示意 SQL：

```sql
SELECT r.*
FROM reservation AS r
JOIN (
  SELECT id
  FROM reservation
  WHERE user_id = :user_id
  ORDER BY id DESC
  LIMIT :page_size OFFSET :offset
) AS page_ids ON page_ids.id = r.id
ORDER BY r.id DESC;
```

已接入预约、审批、报修、通知、设备、用户和实验室列表。`OFFSET` 仍需扫描跳过的索引项，
延迟关联主要避免深页先读取大量完整行；后端最多允许跳过 100,000 条匹配记录，超出后由页面提示增加筛选。

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
