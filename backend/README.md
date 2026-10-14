# 兼容存储目录

原业务附件继续保存在忽略版本控制的 `.data/uploads/`，不移动或删除数据。后端源码、构建、迁移与测试入口均位于 [backend-java](../backend-java/README.md)，本目录不再提供 Python 工具或 Alembic 运行入口。

`benchmarks/non_ai_load_profiles.js` 是可选的 k6 HTTP 压测工具。历史容量报告仅供参考，不代表当前版本的验证结果。
