# ADR 0043：移除 Python 工具链

状态：已接受。日期：2026-10-14。

用户确认仓库不再依赖 Python，业务数据继续保留。本决定取代 ADR 0041 中在当前 checkout 保留 Alembic Python 源码的安排。

删除旧后端映射与配置、Python 造数和通知工具、历史性能及验收脚本、Python 依赖清单和 Alembic 源码，共 123 个 Python 文件。历史文字报告保留并标明版本；旧实现可通过 Git 历史核验。已执行的 Flyway V1–V5 SQL 不变，也不改写数据库中的迁移版本记录。

标准 Playwright 测试改用 Java JAR 的一次性 CLI，通过指定测试学院创建及清理数据。CLI 拒绝业务库名和非测试前缀，自动关闭 Worker、Streams 消费及管理员初始化；不新增测试 HTTP 接口。通知造数、Outbox 批量通知、Stream 检查和测试消费组清理也改为 Java。旧账号的 Argon2 密码兼容用公开固定哈希验证。

现有 MySQL、Redis、业务附件路径和存储卷保留。更早的 Alembic 数据库需要先使用历史版本升级至 0038，再执行既有 Java 基线流程。当前版本只要求 Java 21、Node.js/pnpm 和业务服务依赖。
