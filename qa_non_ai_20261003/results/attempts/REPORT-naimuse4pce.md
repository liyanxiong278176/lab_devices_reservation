# 非 AI 前后端全链路联调记录

- 执行时间：2026-10-03T12:51:07.214Z 至 2026-10-03T12:52:23.155Z
- 真实链路：Vue/Vite http://127.0.0.1:5173 → FastAPI http://127.0.0.1:8001 → 当前 MySQL/Redis。
- 测试入口：本目录新建的 runner.cjs；没有调用 backend/tests、frontend/e2e 或既有联调 spec。
- 非 AI API 操作：78/107（72.9%；每个 OpenAPI method/path 至少一次实际 HTTP 请求）。
- 非 AI 页面路由截图：20；管理员页面目标数为 20。
- 页面运行时异常：0；HTTP 5xx：0。
- 结果：**INCOMPLETE**

## 场景结果

| 场景 | 结果 | 备注 |
|---|---|---|
| 登录、身份读取、Refresh 轮换与系统健康/Outbox 查询 | PASS |  |
| 公开注册入口尝试 | LIMITED | POST /auth/register HTTP 429；该共享 IP 配额已耗尽，当前角色由管理端创建 |
| 学院/实验室/用户/角色管理 CRUD，普通账号注册与负责人登录 | PASS |  |
| 设备与资源池读写、状态历史、安全须知和资质上传审核 | PASS |  |
| 系统管理员 20/20 个非 AI Vue 页面路由和截图 | PASS |  |
| Vue 预约表单 → 审批/签到/交接 → 归还/验收 → 使用评价 | PASS | reservation_id=235515 |
| 驳回/批量审批、取消预约、候补递补/确认/取消 | PASS |  |

## 未覆盖的 OpenAPI 操作

- DELETE /api/v2/blackouts/{blackout_id}
- DELETE /api/v2/reservation-rules/{rule_id}
- GET /api/v2/blackouts
- GET /api/v2/dashboard/summary
- GET /api/v2/device-pools/options
- GET /api/v2/maintenance-plans/{plan_id}/records
- GET /api/v2/repair-reports/{report_id}/worklogs
- GET /api/v2/reports/export/{export_type}
- GET /api/v2/reports/exports/{task_id}
- GET /api/v2/reservations/handovers
- GET /api/v2/reservations/mine
- PATCH /api/v2/notifications/read-all
- PATCH /api/v2/notifications/{notification_id}/read
- POST /api/v2/auth/logout
- POST /api/v2/blackouts
- POST /api/v2/devices/{device_id}/maintenance-evidence
- POST /api/v2/devices/{device_id}/maintenance-plans
- POST /api/v2/maintenance-plans/{plan_id}/records
- POST /api/v2/repair-reports
- POST /api/v2/repair-reports/{report_id}/confirm
- POST /api/v2/repair-reports/{report_id}/reject
- POST /api/v2/repair-reports/{report_id}/resolve
- POST /api/v2/repair-reports/{report_id}/take
- POST /api/v2/reports/exports
- POST /api/v2/reservations/{reservation_id}/cancel-handover-exception
- POST /api/v2/reservations/{reservation_id}/violate
- POST /api/v2/system/outbox/{task_id}/retry
- PUT /api/v2/maintenance-plans/{plan_id}
- PUT /api/v2/reservation-rules

## 证据和范围

- integration-results.json 保存结构化结果和资源 ID；报告不包含 cookie、CSRF 值或密码。
- screenshots/ 保存实际浏览器页面截图；账号、学院、实验室与设备均使用本轮唯一前缀。
- 100% method/path 覆盖不等于 Python/TypeScript 源码行或分支覆盖。源码覆盖率需要在启用 instrumentation 的进程中单独测量。
- 隔离联调数据保留在本地数据库；没有清理原有数据、容器或服务。
