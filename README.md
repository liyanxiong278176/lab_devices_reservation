# LabFlow 实验室设备预约系统

## 项目背景

LabFlow 面向高校实验室的设备共享与管理，支持普通用户按自然日预约设备，以及管理员审批、现场交接、归还验收、报修处理、违约处罚和申诉。系统按学院隔离数据，并提供消息通知和 AI 知识库助手。

后端使用 Python 3.13 / FastAPI，前端使用 Vue 3 / TypeScript / Element Plus，依赖 MySQL 8、Redis 7 和 Qdrant。

## 安装使用

准备 Python 3.13、uv、Node.js、pnpm 和 Docker Desktop。以下命令在 PowerShell 中执行。

### 1. 配置环境并启动依赖

在项目根目录执行（已有 `.env` 时保留原文件）：

```powershell
Copy-Item .env.example .env
```

按模板填写 `.env` 中的数据库密码、JWT 密钥及 Compose 必填项。`LAB_MYSQL_DSN` 中的账号、密码应与 `DB_APP_USER`、`DB_APP_PASSWORD` 一致；设置 `LAB_BOOTSTRAP_ADMIN_PASSWORD` 作为首次创建 `admin` 的密码。

```powershell
docker compose up -d mysql redis qdrant
```

若本机使用独立版 Compose，将 `docker compose` 替换为 `docker-compose`。

### 2. 安装并启动后端

从项目根目录执行：

```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --loop app.core.uvicorn_loop:platform_loop_factory --host 127.0.0.1 --reload --port 8000
```

后端接口文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

### 3. 安装并启动前端

另开终端，从项目根目录执行：

```powershell
cd frontend
pnpm install
pnpm dev
```

浏览器访问 [http://localhost:5173](http://localhost:5173)。普通用户可在登录页注册；管理员使用 `admin` 和配置的初始化密码登录，已有账号的密码不会被覆盖。

当前工作区的本地测试账号：普通用户 `zhangsan / 123456`，系统管理员 `admin / admin123`。

推送到 `main` 或 `master` 后，自动部署会在数据库迁移完成后为三个预置学院补齐示例设备和维护计划（空库共 18 台设备、18 个计划）。重复部署不覆盖已有设备、维护计划或账号密码；示例数据可在管理页面编辑。

### 4. 可选：初始化演示数据与 AI 知识库

首次使用空库时，可在完成迁移后从 `backend` 目录初始化学院、实验室、设备和 `zhangsan` 普通用户（仅限本地开发）：

```powershell
$env:LAB_DEMO_USER_PASSWORD = '123456'
$env:LAB_DEMO_MANAGER_PASSWORD = '<负责人密码>'
uv run python scripts/seed_demo_data.py
```

脚本还需 `.env` 已配置 `LAB_BOOTSTRAP_ADMIN_PASSWORD`，已有记录不会重复创建。

使用 AI 功能时，在根目录 `.env` 填写对应的 AI 服务凭据并重启后端；需要构建知识库时，另开终端从 `backend` 目录启动 Worker：

```powershell
uv run celery -A app.infrastructure.tasks.celery_app:celery_app worker --pool=solo --loglevel=INFO --concurrency=1 --prefetch-multiplier=1 --queues=knowledge-build
```

## 前端流程截图册

[完整截图册，用浏览器打开逐张查看（242 张）](.artifacts/browser-flow-20261007/viewer/gallery.html)

截图覆盖普通用户与管理员的预约审批、设备交接与归还验收、报修处理、违约处罚和申诉，以及管理员周期保养、仪器校准、安全检查与维修复测流程。入口对应当前工作区的本地测试产物。
