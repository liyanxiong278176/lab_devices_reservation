# 历史迁移及可选验证工具

HTTP 后端已迁移到 [../backend-java](../backend-java/README.md)。此目录不包含 FastAPI、Uvicorn、Celery 或 AI 运行代码。

- `migrations/`：已执行的 Alembic revisions 原样保留；旧库基线要求 `0038_penalties_overdue`。只用于迁移来源核验和旧版本升级，不用于初始化新 Java 数据库。
- `app/`：仅保留浏览器 fixture 和 SQL/Redis 运维工具需要的业务表映射、密码哈希与配置。
- `scripts/e2e_fixture.py`：隔离的多角色浏览器测试数据；唯一 `e2e-` 前缀。
- `scripts/e2e_notification_stream.py`、通知 stream_ops：通知检查、测试数据与人工恢复工具；生产消费者由 Java 实现。
- `scripts/remove_ai_resources.py`：维护期间仅删除本项目 AI 文件及已确认的向量集合，保护业务附件；默认只检查。
- `benchmarks/`：通过 HTTP 测量 Java 服务及 SQL 查询；旧 Python Worker/API 专用探针已移除。

```powershell
uv sync
uv run ruff check app scripts
```

Python 和 uv 只在使用这些工具时需要。根目录 `.env` 是唯一配置文件。测试先设置指向隔离库的 `LAB_MYSQL_DSN` 和独立 Redis DB；不能让测试工具操作真实业务数据。
