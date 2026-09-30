# SSE 通知流测试说明

## 测试目标与分层

围绕 `GET /api/v2/notifications/stream` 验证通知可靠投递和访问隔离。测试分为三层：

- **单元测试**：验证 SSE 事件生成、`NotificationHub` 会话关闭和前端序号去重，不启动 HTTP 服务。
- **接口测试**：通过 HTTPX `ASGITransport` 请求 FastAPI 路由，检查 SSE 响应头、事件正文及当前用户/学院范围。
- **集成测试**：使用 MySQL 验证多个独立事务并发分配序号；Redis Pub/Sub 多进程唤醒由现有 relay 测试覆盖。

`backend/tests/test_notification_sse.py` 文件头和测试函数说明标注了层级。SQLite 仅用于单元和接口逻辑验证，不能作为 MySQL `SELECT ... FOR UPDATE` 并发行为的证据。

## 执行方法

在 `backend` 目录运行 SSE 相关的单元、接口及 Redis 模拟 relay 测试：

```powershell
uv run pytest -q tests/test_notification_sse.py tests/test_notifications.py tests/test_notification_relay.py
```

MySQL 并发集成测试默认跳过。确认 `.env` 中的 MySQL 测试库可用后，在 `backend` 目录运行：

```powershell
$env:LAB_RUN_MYSQL_INTEGRATION = '1'
uv run pytest -q tests/test_notification_sse.py -k mysql_concurrent_notification_creation
Remove-Item Env:LAB_RUN_MYSQL_INTEGRATION
```

该测试会创建带随机前缀的临时学院和用户，并在结束时清理；不要指向生产数据库。

前端 EventSource 和通知 store 单元测试，在 `frontend` 目录运行：

```powershell
pnpm test -- --run src/composables/__tests__/useEventStream.test.ts src/stores/__tests__/notification.test.ts
```

真实浏览器断流重连和多标签页已读同步链路由现有 Playwright 用例覆盖：

```powershell
pnpm exec playwright test e2e/notification-reconnect.spec.ts
```

## 场景与预期结果

| 编号 | 层级 | 测试场景 | 预期结果 |
|---|---|---|---|
| SSE-U01 | 单元 | 有效通知写入 MySQL，用户流收到唤醒 | SSE 输出 `notification` 事件，事件 ID 等于用户序号，正文来自持久化通知行 |
| SSE-U02 | 单元 | 使用 `Last-Event-ID=N` 重连 | 只输出序号大于 N 的通知，按序号升序排列；重复唤醒不重复业务投递 |
| SSE-U03 | 单元 | 注销当前会话 | 对应流结束并输出终止用的 `auth-revoked`；其他用户流不受影响 |
| SSE-I01 | 接口 | GET SSE 路由并携带有效会话 | 返回 200、`text/event-stream`、禁止缓存响应头；用户身份来自会话，不从 URL 参数读取 |
| SSE-I02 | 接口/权限 | 学院 A 用户尝试通过 `user_id` 查询参数访问学院 B 通知 | 只返回当前会话用户且在当前学院范围内的通知，不返回学院 B 的通知 |
| SSE-I03 | 接口/权限 | 缺少 Cookie、通知读取权限被撤销或会话失效 | 未认证/无权限请求被拒绝；已建立流在权限复核或会话主动撤销后关闭 |
| SSE-I04 | 接口/边界 | 畸形、负数或超过 BIGINT 范围的 `Last-Event-ID` | 请求返回明确的游标错误，不建立可绕过数据范围的流 |
| SSE-I05 | 接口/积压 | 游标后积压 105 条通知 | SSE 最多发 100 条；摘要报告 5 条未由 SSE 重放，并提示前端刷新 HTTP 历史和未读数；较早历史仍可分页查询 |
| SSE-M01 | MySQL 集成 | 16 个独立事务同时为同一用户创建通知 | 用户序号唯一、连续递增；按 SSE 查询结果输出时仍严格升序，无重复 ID |
| SSE-F01 | 前端单元 | EventSource 连接收到 `error` 后自动重连 | 复用同一 EventSource，重连事件按服务器下发的序号交给通知 store |
| SSE-F02 | 前端单元 | 重连重放同一序号 | store 忽略重复序号，不重复弹通知；其他新序号仍正常显示 |
| SSE-R01 | Redis 集成/模拟 | 一个进程发布通知或已读状态，其他进程有该用户流 | 只唤醒该用户在线流；消息正文和顺序仍以 MySQL 为准 |

## 测试报告模板

复制下表用于每轮执行记录。接口结果、MySQL/Redis 版本和提交版本应与实际环境一致；未执行的项保留“未执行”，不要推定通过。

| 测试项 | 预期结果 | 实际结果 | 状态 | 证据/备注 |
|---|---|---|---|---|
| SSE-U01 实时消息 | 收到匹配持久化行的 SSE 通知和用户序号 | 待填写 | 未执行 |  |
| SSE-U02 Last-Event-ID 顺序重放 | 仅重放游标之后的消息，按序升序 | 待填写 | 未执行 |  |
| SSE-U03 注销断流 | 该会话收到终止事件并关闭 | 待填写 | 未执行 |  |
| SSE-I01 SSE HTTP 契约 | 200、SSE Content-Type、禁止缓存 | 待填写 | 未执行 |  |
| SSE-I02 学院隔离 | 不返回其他用户/学院通知 | 待填写 | 未执行 |  |
| SSE-I03 会话和权限失效 | 拒绝新请求或关闭已建立流 | 待填写 | 未执行 |  |
| SSE-I04 游标校验 | 非法游标请求被拒绝 | 待填写 | 未执行 |  |
| SSE-I05 超 100 条积压 | SSE 不超过 100 条，HTTP 历史可补查 | 待填写 | 未执行 |  |
| SSE-M01 MySQL 并发序号 | 16 个并发事务分配连续唯一序号，投递有序 | 待填写 | 未执行 | 记录 MySQL 版本及命令 |
| SSE-F01 前端断线重连 | 同一 EventSource 在断线后继续接收 | 待填写 | 未执行 |  |
| SSE-F02 前端幂等去重 | 重放相同序号不重复通知 | 待填写 | 未执行 |  |
| SSE-R01 Redis 多进程唤醒 | 仅目标用户各在线流收到唤醒 | 待填写 | 未执行 | 记录 Redis 版本及命令 |

**执行环境：** OS / Python / FastAPI / MySQL / Redis / Node / 浏览器  
**代码版本：**  
**执行人及时间：**  
**总体结论：** 通过 / 有条件通过 / 未通过  
**未通过项与后续处理：**

## 当前验证发现

2026-09-29 的首次执行发现超 100 条积压时，查询取了最旧的 100 条，却将游标推进到最高序号，和“重放最新 100 条”的预期不符。实现已调整为先选择最新 100 条，再升序发出；积压 105 条时序号 `6–105` 被 SSE 重放，较早的 `1–5` 保留给 HTTP 历史查询。对应回归测试现已通过。

本轮执行记录：后端全量测试 **515 passed、20 skipped**；启用 MySQL 集成开关后，并发序号测试 **1 passed**；前端全量测试 **353 passed**；Ruff 检查通过。
