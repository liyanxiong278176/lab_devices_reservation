# LabFlow 实验室设备预约系统

面向高校实验室的设备共享平台，支持自然日预约、资源池、多角色审批、候补、设备交接、归还验收、报修、维护校准、安全准入、处罚申诉、报表与通知。学院是租户边界。

后端为 **Java 21 / Spring Boot / MyBatis / Flyway**，前端为 Vue 3 / TypeScript / Element Plus，依赖 MySQL 8 和 Redis 7。AI 工作台、知识库及 AI 运行依赖已移除。

## 本地启动

准备 JDK 21、Node.js、pnpm、Docker；已有 `.env` 时保留原文件，首次配置执行：

```powershell
Copy-Item .env.example .env
docker compose up -d mysql redis
cd backend-java
.\mvnw.cmd package
```

按 `.env.example` 填写数据库账号、JWT 密钥和监控配置。`LAB_MYSQL_DSN` 兼容原来的连接串，也可使用 `LAB_JDBC_URL`、`LAB_DB_USERNAME`、`LAB_DB_PASSWORD`。环境变量优先于根目录 `.env`。

**全新空库**在 `backend-java` 执行初始化：

```powershell
java -jar target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=migrate
java -jar target/labflow-backend-1.0.0.jar
```

**已有业务库**必须走[保留业务数据的切换步骤](docs/springboot-cutover.md)，先核验旧迁移版本并显式 baseline；不能对已有库执行空库建表流程。默认不自动迁移、不自动 baseline。

配置 `LAB_BOOTSTRAP_ADMIN_PASSWORD`（至少 12 字符）可创建首次管理员，已有账号和密码不会覆盖。设备和组织可在管理页面维护。

另开终端启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

页面：[http://localhost:5173](http://localhost:5173)；接口文档：[http://127.0.0.1:8000/api/v2/docs](http://127.0.0.1:8000/api/v2/docs)。接口保持 `/api/v2`。

## 验证

Java 检查见 [backend-java/README.md](backend-java/README.md)。前端执行 `pnpm build`、`pnpm test`、`pnpm test:e2e`。真实数据库测试必须指定隔离测试库，不能使用业务库。

`backend/` 仅保留历史 Alembic 迁移与可选 SQL/Redis 验证工具，不提供 Python HTTP 服务。浏览器验收的 fixture 工具需要 Python 3.13 和 uv，执行 `uv sync --project backend`；Java 运行和 Docker 镜像不需要 Python。

现有本地[前端截图册](.artifacts/browser-flow-20261007/viewer/gallery.html)属于验收产物，不是应用运行入口。
