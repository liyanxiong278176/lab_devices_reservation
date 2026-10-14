# 实时通知 Redis Stream 专项联调结果

运行前缀：`e2e-musfaeli`

| 用例 | 前置条件 | 操作步骤 | 预期结果 | 实际结果 | 是否通过 | 截图证据 |
|---|---|---|---|---|---|---|
| 01 正常实时推送 | 测试用户已登录，SSE EventSource 返回 200，API 使用独立 Redis DB 14。 | 写入一条 NOTIFICATION Outbox 任务，等待消费、Stream ACK 和通知中心更新。 | 前端及时显示通知；CDP Network 捕获 SSE notification 事件和序号。 | 测试结束状态：failed；详见对应 Network、Redis/MySQL/监控证据。 | 失败 | [case-01-frontend.png](./case-01-frontend.png)<br>[case-01-sse-network.png](./case-01-sse-network.png) |

通过 0/1 条。
