# Spring Boot 后端

Java 21、Spring Boot 3.5、MyBatis、Spring 事务、Flyway；MySQL 是业务事实源，Redis 保存会话并负责限流、名额预占和 Streams 实时通知。HTTP 接口保持 `/api/v2`，后台任务由同进程有界 MySQL Outbox Worker 处理。

## 构建与运行

```powershell
.\mvnw.cmd clean verify
java -jar target/labflow-backend-1.0.0.jar
```

读取仓库根目录 `.env`，进程环境变量和命令行配置优先。默认端口 8000。保留原 `LAB_MYSQL_DSN=mysql+asyncmy://...` 配置格式，也支持 JDBC 设置。旧上传文件路径继续使用 `backend/.data/uploads`；生产 Compose 保留原 `app_data` 卷。

`LAB_BOOTSTRAP_ADMIN_PASSWORD` 只创建不存在的管理员，不修改已有账号。生产环境要求私有数据库密码、JWT secret 和安全 Cookie。

## 数据迁移

详见 [切换说明](../docs/springboot-cutover.md)。`verify`、`baseline`、`migrate` 均使用一次性 CLI，执行期间自动停用后台 Worker 和通知消费。已有库先验证 Alembic 0038 和业务表结构再显式基线 1；新库直接执行 V1。后续迁移删除 AI 专属表和共享表中的已知 AI 记录。

## 自动验证

不设置集成环境时只运行独立单元测试。真实 MySQL/Redis 测试需要：

- `LAB_JDBC_URL=jdbc:mysql://127.0.0.1:33306/labflow_migration_test_fresh`、`LAB_DB_USERNAME`、`LAB_DB_PASSWORD`。
- `LAB_TEST_MYSQL_URL=jdbc:mysql://127.0.0.1:33306/labflow_migration_test`、`LAB_TEST_MYSQL_PASSWORD`，该库先应用原 Alembic 0038，用于基线演练。
- `LAB_REDIS_URL=redis://127.0.0.1:36379/14`、`LAB_ENVIRONMENT=test`、`LAB_JWT_SECRET`（测试专用，32 字符以上）、`LAB_COOKIE_SECURE=false`。
- `LAB_ENABLE_WORKERS=false`、`LAB_ENABLE_NOTIFICATION_RELAY=false`。
- `LAB_TEST_PYTHON_ARGON2_HASH`：用 pwdlib 对公开测试密码 `python-compatibility-test` 生成的哈希，验证旧密码兼容。

初始化隔离空库后执行 `.\mvnw.cmd verify`；集成测试通过库名保护拒绝业务库。覆盖设备日并发唯一约束、事务、请求幂等、学院隔离、Cookie/CSRF/刷新轮换和迁移保存业务数据。

代码格式：`.\mvnw.cmd spotless:apply`；前端 E2E 在 `frontend/` 执行，先打包 Java JAR，并通过 `E2E_API_URL`、`E2E_BACKEND_PORT` 和 `VITE_API_PROXY_TARGET` 指向测试 API。

集成测试和浏览器 API Worker 不能同时处理同一个隔离库；分阶段运行，先停止浏览器测试 API，再执行 Outbox 集成测试。通知专项运维套件需两套 Java API、独立 Redis DB 14 和 Prometheus/Grafana，使用 `E2E_NOTIFICATION_LIVE=1` 或专项 Playwright 配置显式启用；普通 E2E 不会自动启动这些外部依赖。
