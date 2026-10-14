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

V4/V5 进一步移除违规申诉、信用处罚、计划维护/校准及逾期流程的专属历史、权限、任务与附件，详见 [流程精简验收](../docs/workflow-removal-verification.md)。普通报修及归还验收保留；首日未领用自动取消，已领用实物在验收前保持占用。

## 自动验证

不设置集成环境时只运行独立单元测试。真实 MySQL/Redis 测试需要：

- `LAB_JDBC_URL=jdbc:mysql://127.0.0.1:33306/labflow_migration_test_fresh`、`LAB_DB_USERNAME`、`LAB_DB_PASSWORD`。
- `LAB_TEST_MYSQL_URL=jdbc:mysql://127.0.0.1:33306/labflow_migration_test`、`LAB_TEST_MYSQL_PASSWORD`，该库先应用原 Alembic 0038，用于基线演练。
- `LAB_REDIS_URL=redis://127.0.0.1:36379/14`、`LAB_ENVIRONMENT=test`、`LAB_JWT_SECRET`（测试专用，32 字符以上）、`LAB_COOKIE_SECURE=false`。
- `LAB_ENABLE_WORKERS=false`、`LAB_ENABLE_NOTIFICATION_RELAY=false`。
旧 Argon2 密码兼容测试使用固定的公开测试哈希，不需要额外运行时或环境变量。

初始化隔离空库后执行 `.\mvnw.cmd verify`；集成测试通过库名保护拒绝业务库。覆盖设备日并发唯一约束、事务、请求幂等、学院隔离、Cookie/CSRF/刷新轮换和迁移保存业务数据。

代码格式：`.\mvnw.cmd spotless:apply`；前端 E2E 在 `frontend/` 执行，先打包 Java JAR，并通过 `E2E_API_URL`、`E2E_BACKEND_PORT` 和 `VITE_API_PROXY_TARGET` 指向测试 API。

集成测试和浏览器 API Worker 不能同时处理同一个隔离库；分阶段运行，先停止浏览器测试 API，再执行 Outbox 集成测试。通知专项运维套件需两套 Java API、独立 Redis DB 14 和 Prometheus/Grafana，使用 `E2E_NOTIFICATION_LIVE=1` 或专项 Playwright 配置显式启用；普通 E2E 不会自动启动这些外部依赖。

## 浏览器测试数据

Playwright 通过 `frontend/e2e/java-command.ts` 调用同一 JAR，无新增测试 HTTP 接口。CLI 自动禁用 Worker、通知消费及管理员初始化，执行后退出。

```powershell
java -jar target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.fixture=seed --prefix=e2e-example123
java -jar target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.fixture=cleanup --prefix=e2e-example123
```

先将数据库和 Redis 配置指向隔离测试服务，库名必须含 `test` 或 `e2e`。`seed` 支持 `--pool-units=1..20`；清理仅针对指定测试学院的账号及精确匹配的初始测试账号，保留其他数据与文件。通知造数、Outbox 批量发送和 Streams 检查同样使用该 CLI；Streams 写操作限定本机 Redis DB 14。

旧 Alembic 源码已退出当前版本；V1 保留原 0038 结构快照，V2–V5 及既有 Flyway 校验值不变。需要升级更早的旧库时，先使用迁移前的 Git 版本升级至 0038，再按切换说明基线。
