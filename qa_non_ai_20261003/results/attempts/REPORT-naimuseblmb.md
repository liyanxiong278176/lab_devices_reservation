# 非 AI 前后端全链路联调记录

- 执行时间：2026-10-03T12:56:28.979Z 至 2026-10-03T12:58:39.248Z
- 真实链路：Vue/Vite http://127.0.0.1:5173 → FastAPI http://127.0.0.1:8001 → 当前 MySQL/Redis。
- 测试入口：本目录新建的 runner.cjs；没有调用 backend/tests、frontend/e2e 或既有联调 spec。
- 非 AI API 操作：107/107（100%；每个 OpenAPI method/path 至少一次实际 HTTP 请求）。
- 非 AI 页面路由截图：40；管理员页面目标数为 20。
- 页面运行时异常：0；HTTP 5xx：0。
- 结果：**PASS**

## 场景结果

| 场景 | 结果 | 备注 |
|---|---|---|
| 登录、身份读取、Refresh 轮换与系统健康/Outbox 查询 | PASS |  |
| 公开注册入口成功与限流响应 | PASS | 本轮 POST /auth/register HTTP 201；注册后登录成功 |
| 学院/实验室/用户/角色管理 CRUD，普通账号注册与负责人登录 | PASS |  |
| 设备与资源池读写、状态历史、安全须知和资质上传审核 | PASS |  |
| 系统管理员 20/20 个非 AI Vue 页面路由和截图 | PASS |  |
| Vue 预约表单 → 审批/签到/交接 → 归还/验收 → 使用评价 | PASS | reservation_id=235532 |
| 驳回/批量审批、取消预约、候补递补/确认/取消 | PASS |  |
| 同设备并发唯一占用、违规信用事件、损坏交接/维修/预约释放 | PASS | race=201,409 |
| 不可预约日和预约规则配置/过滤/删除 | PASS |  |
| 故障图片、报修/接单/解决/用户确认，以及驳回/退回 | PASS |  |
| 维护计划、周期完成记录、附件与历史记录 | PASS |  |
| 仪表盘、报表导出、推荐、通知历史/已读与浏览器 SSE | PASS |  |
| 学院边界验证与 Outbox retry 路由的无效任务拒绝 | PASS |  |
| 联调浏览器会话登出 | PASS |  |

## 未覆盖的 OpenAPI 操作

- 无

## 证据和范围

- integration-results.json 保存结构化结果和资源 ID；报告不包含 cookie、CSRF 值或密码。
- screenshots/ 保存实际浏览器页面截图；账号、学院、实验室与设备均使用本轮唯一前缀。
- 100% method/path 覆盖不等于 Python/TypeScript 源码行或分支覆盖。源码覆盖率需要在启用 instrumentation 的进程中单独测量。
- 隔离联调数据保留在本地数据库；没有清理原有数据、容器或服务。
