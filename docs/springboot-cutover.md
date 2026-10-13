# 保留业务数据的 Spring Boot 切换

按 ADR 0041：AI 历史直接删除，不导出、不归档；已有业务数据、旧账号密码和附件保留。此流程用于旧 Alembic `0038_penalties_overdue` 业务库。先在隔离库演练，再在维护窗口暂停写入并停止旧 API、Python Outbox、定时任务和 Celery Worker。

## 核验及基线

打包 Java 后在仓库根目录执行，所有命令读取根目录 `.env`：

```powershell
java -jar backend-java/target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=verify
java -jar backend-java/target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=baseline
```

`verify` 检查业务列、类型、非空、唯一约束和外键。`baseline` 还要求唯一 Alembic head 为 0038；校验不通过时拒绝基线，不猜测版本、不清库。基线为 1，后续 V2/V3 仅清理 AI 表、权限和已知 AI 专属共享记录。空库直接 `migrate`，不执行 `baseline`。

停写期间保存非 AI 业务表的备份、记录数和校验值。共享通知、审计、Outbox、权限及角色权限备份只保留非 AI 记录。AI 历史不能混入备份。不要修改已执行 Alembic 或 Flyway 文件。

## 清理 AI 专属资源

必须在删表前完成所有权清单，因为专属文件、向量集合和 Celery task ID 来自旧表：

```powershell
uv run --project backend python backend/scripts/remove_ai_resources.py --vector-url http://127.0.0.1:6333 --broker-url redis://127.0.0.1:6379/1
uv run --project backend python backend/scripts/remove_ai_resources.py --apply --old-processes-stopped --vector-url http://127.0.0.1:6333 --broker-url redis://127.0.0.1:6379/1 --remove-ai-config
```

使用实际端点，先检查默认只读输出。只处理 `uploads/ai-knowledge`，保留 `v2_upload_asset` 引用的业务文件，遇到符号链接拒绝操作。Qdrant 集合来自本库 active/rebuild 索引记录和显式配置；不删除其他项目集合。Redis 仅处理 `knowledge-build` 队列、对应绑定/优先级队列、本库构建任务结果及该队列 unacked 项；不清空 Redis、不删除业务 Stream 或其他队列。配置清理仅删除根 `.env` 中 `LAB_AI_*`、`LAB_QDRANT_*`、`LAB_CELERY_*`。

本地 `lab-qdrant` 容器也可能被其他项目使用；不能仅依据 Compose 标签删容器或卷。专属集合已清理后，保留共享服务给其他项目使用。独占的旧 Celery/Qdrant 运行服务可在核实无其他用途后退出。

## 迁移、登录失效及启动

```powershell
java -jar backend-java/target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=migrate
java -jar backend-java/target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=invalidate-sessions
java -jar backend-java/target/labflow-backend-1.0.0.jar --spring.main.web-application-type=none --labflow.migration=verify
```

CLI 自动禁用 Worker 和 Streams 消费，迁移期间不执行业务任务。登录失效只清理本项目 Redis session/user-session 前缀，用户需要重新登录。

核对非 AI 表记录数和校验值、主键外键、附件引用；授权版本应递增。先以 `LAB_ENABLE_WORKERS=false` 启动 Java 并验证 `/api/v2/live`、`/api/v2/ready`、登录和页面链路，再按正常配置启用 Worker 并开放写入。旧、新 Worker 不能处理同一业务库。正常后台任务执行后，业务数据自然会变化，因此迁移前后核对必须在 Worker 启动前完成。

Docker 保留原 `mysql_data`、`redis_data`、`app_data` 卷。首次以 UID 10001 运行前，用一次性 root 容器把 `/app/backend/.data` 的所有权交给 10001；不移动或删除业务文件。后续部署流程只执行已基线库的 `migrate`，首次人工基线必须先完成，否则自动部署会失败关闭。

恢复仅针对保留的非 AI 业务；清理后的 AI 历史没有恢复副本。
