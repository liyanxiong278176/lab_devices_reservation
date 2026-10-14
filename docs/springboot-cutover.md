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

当前工作区已完成 AI 专属文件、向量集合和队列清理，相关旧工具随 Python 源码移除。此前的清理结果见迁移验收记录，不重新删除共享服务或业务附件。

对尚未切换的旧安装，应在删表前使用迁移前的 Git 版本完成专属资源所有权核验和清理，再切回本版本执行 SQL 迁移。不得清空 Redis 或删除其他项目的 Qdrant 集合；原有业务存储卷继续保留。

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
