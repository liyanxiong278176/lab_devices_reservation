# ADR-0013：使用 LangChain + LangGraph 构建 Agent Harness

- 状态：已接受
- 日期：2026-08-26
- 决策人：项目负责人

## 决策

AI 系统采用分层结构：

- LangChain 负责模型适配、结构化工具、Prompt、Retriever 和输出解析。
- LangGraph 负责 Agent Harness 的状态图、节点编排、流式事件、人工确认中断、恢复和失败重试。
- FastAPI 负责鉴权、会话 API、WebSocket/SSE、任务入口和领域服务调用。
- MySQL 负责预约、确认动作、工具执行、审计和业务状态的最终事实来源。

Agent 的典型流程是：理解请求 → 判断走文档检索还是结构化工具 → 组合检索/查询结果 → 生成方案 → 对写操作发起确认中断 → 调用领域服务执行 → 校验结果 → 返回带引用和执行轨迹的回答。

生产环境不能使用只存在进程内的 Graph state 或 `InMemorySaver`。LangGraph 的 checkpoint 必须落到持久化存储，并与会话、用户、学院和执行记录关联；具体 MySQL 适配方式在实现阶段验证。

Agent 编排层不能绕过后端授权、事务和并发控制，也不能把模型输出当成业务成功凭证。

## 影响

- 支持“等待用户确认后继续”、断线重连、长流程和多步工具调用。
- 增加了状态序列化、checkpoint 清理、版本兼容和图迁移成本。
- LangGraph 不是新的业务微服务，仍然运行在单体 FastAPI 应用内。
