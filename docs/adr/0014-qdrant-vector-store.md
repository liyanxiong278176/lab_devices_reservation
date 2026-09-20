# ADR-0014：使用 Qdrant 作为 Agentic RAG 向量存储

- 状态：已接受
- 日期：2026-08-26
- 决策人：项目负责人

## 决策

Agentic RAG 使用 Qdrant 保存文档 chunk 的向量和检索 metadata；MySQL 继续保存文档原件引用、版本、审核状态、生效时间、学院范围、索引任务和删除/撤回记录。

每个向量至少携带文档 ID、chunk ID、学院范围、文档类型、版本和生效状态。全校文档使用显式的 global scope，学院文档使用 `college_id`。检索必须同时经过：

1. FastAPI 根据认证上下文验证用户学院和文档访问范围；
2. Qdrant query 使用不可由用户覆盖的 metadata filter。

Qdrant 不是权限系统，向量过滤也不能替代业务授权；所有引用片段仍需回查 MySQL 文档状态并在回答中保留来源。

## 选择原因

- 在不迁移 MySQL 的前提下提供专用向量检索能力。
- 支持 payload 过滤和租户/学院 metadata 组织，适合制度、手册和 SOP 的范围检索。
- Python 客户端和 LangChain 集成路径清晰，部署复杂度低于面向超大规模的分布式向量平台。

## 影响

- 增加一个需要持久化、备份、监控和版本管理的基础设施组件。
- 必须处理 Qdrant 与 MySQL 的索引一致性：文档发布、撤回或重建不能只更新一边。
- 嵌入模型或向量维度变化时需要新 collection/namespace 和可回滚重建流程。
- 当前阶段需进一步确定“单 collection + 强制学院 filter”还是“每学院独立 collection/分片”的隔离布局。
