# 双角色前后端联调报告

## 最新复测（2026-10-03，Asia/Shanghai）

- 真实 Vue、FastAPI、MySQL、Redis、Qdrant 浏览器回归 **9/9 通过**，耗时约 2.4 分钟；执行详情保存在 `playwright.json`。
- 两个普通用户同设备同自然日并发：响应 **201/409**，MySQL 只保留 1 条预约占用；管理员待审批列表也只有 1 条。
- Redis 容器真实停机期间，普通用户和管理员真实页面请求均收到 **503 `AUTH_SESSION_UNAVAILABLE`**；E11 断言右上角显示“登录服务暂时不可用，请稍后重试”。启动 Redis 后两角色会话均恢复为 **200**，普通用户预约记录前后 **1/1 且 ID 相同**。
- MySQL/Redis 锁集成用例 **6/6 通过**，覆盖 Redis 不可用时 8 个并发提交由 MySQL 唯一约束保证只成功 1 个、其余 7 个返回 409。
- 分页性能复测：隔离数据 **10,000 条预约、100 台设备**；20 并发均匀读取 500 页、每页两次，共 1,000 次；全部 HTTP 200，无传输错误。耗时 **21.174 秒**，吞吐 **47.23 req/s**，p50/p95/p99 **418.34/484.13/603.76 ms**，最大 **629.63 ms**。临时实例关闭了限流并禁用了后台 worker；没有预定义 SLA，因此记录为本机基线，不作 SLA 达标结论。
- 共 **107 张截图**。当前联调服务保留在 `127.0.0.1:8001`（FastAPI）和 `127.0.0.1:5173`（Vue）；压测租户已清理，测试完成后 `qa_joint` 两个学院和账号已重新播种为空数据状态，供手工复看。
- 本次改动只调整前端 `AUTH_SESSION_UNAVAILABLE` 提示和 E11 真实浏览器验证；没有修改后端业务代码或 Alembic 迁移。

详细的前端操作步骤与测试账号见 `qa_joint/README.md`；截图逐项链接见 [截图台账](SCREENSHOT_LEDGER.md)。

## 历史复测（2026-09-30）

日期：2026-09-30（Asia/Shanghai）
方式：真实 Vue 前端、真实 FastAPI、MySQL、Redis 与 Qdrant；普通用户、第二用户、负责人、系统管理员使用独立浏览器上下文。没有 mock 前端或后端。

## 结果摘要

- Playwright 全量运行：**8 项通过，0 项失败，0 项跳过**，约 6 分钟。
- E8 后端停机/恢复：更新 Windows 子进程启动方式后单独复测，**1 项通过，20 秒**。
- `uv run ruff check .`（`backend/`）通过；`uv run ruff check ..\qa_joint\scripts\db_assertions.py` 通过。
- 共 **95 张步骤截图**，见 [截图台账](SCREENSHOT_LEDGER.md)。
- 测试租户 `e2e-joint01`、`e2e-joint02` 已清理，运行时账号索引已删除；由 `qa_joint` 启动的 8001/5173 服务已停止。
- 未修改后端业务代码、迁移或既有迁移文件。

## 场景结果

| 编号 | 验证内容 | 结果与证据 |
|---|---|---|
| S0 | 普通用户和系统管理员分别登录；核对菜单隔离 | 通过。两端独立 Cookie 会话，普通用户看不到审批、设备管理和用户管理入口。截图在 `00-preflight/`。 |
| S1–S8 | 双端可见性、当天预约、审批、图片交接、用户归还、管理员验收、评价、报修受理/解决/用户确认 | 通过。预约及报修均到 `COMPLETED`，设备维修期间为 `MAINTENANCE`，完成后为 `IDLE`。审批时用户页收到实时 SSE 通知；Cookie 检查为 HttpOnly、SameSite=Lax。截图在 `01-normal/`。 |
| E1 | 空账号、错误密码、注入型登录输入 | 通过，均被拒绝。截图在 `04-errors/`。 |
| E2 | 起止日期颠倒、过去日期、超过 8 天、空用途、超长用途 | 通过，页面或 API 均拒绝；未创建预约。截图在 `04-errors/`。 |
| E3 | 两名用户同时预约同设备同日 | 通过：响应分别为 201/409；MySQL 中只有 1 条预约；管理员仅看到一条待审批。截图在 `05-concurrency/`。 |
| E4 | 普通用户访问管理页面/API、访问外学院预约 | 通过：跳转/拒绝，接口为 403 或 404。截图在 `06-scope-approval/`。 |
| E5 | 重复审批、审批已取消预约、审批不存在预约、负责人跨学院审批 | 通过：分别为 409、409、404、403。截图在 `06-scope-approval/`。 |
| E6 | 交接前签到/归还、重复归还 | 通过，非法状态转换被拒绝。截图在 `02-boundaries/`。 |
| E7 | 未受理即完成报修、维修设备仍尝试预约 | 通过，操作被拒绝。截图在 `03-repair-errors/`。 |
| E8 | 后端临时停止，对用户和管理员执行真实请求，再恢复 | 通过：故障期两个角色均收到 502，恢复后两个会话的 `/auth/me` 为 200，列表页面恢复。最终复测用时 20 秒。截图在 `07-recovery/`。 |
| E9 | 登出后浏览器后退、访问受保护页面 | 通过：回到登录页，`/auth/me` 为 401。截图在 `08-session/`。 |
| E10 | 缺少 CSRF、伪造 Origin | 通过：两种写请求均为 403；数据库中均无对应预约行。截图在 `09-write-protection/`。 |

## 契约核查

- API 通过 Vite `/api/v2` 代理访问真实 FastAPI；自然日字段为 `YYYY-MM-DD`，当天全链路使用动态 `dateAfter(0)`，实际日期为 `2026-09-30`。
- 关键状态已从真实 API 响应和页面复核：预约 `PENDING → APPROVED → IN_USE → COMPLETED`；维修期间设备 `MAINTENANCE`，处理完成后为 `IDLE`。
- 已核对实际错误状态：并发冲突 409、越权 403/404、重复或已取消审批 409、缺 CSRF 403、伪造 Origin 403、登出后的身份查询 401。
- 会话 Cookie 由独立浏览器上下文自动携带；访问 Cookie 与 CSRF Cookie 均核对为 HttpOnly、SameSite=Lax。管理员审批后，用户仍打开的页面经 SSE 显示“预约申请已通过”通知，再检查其预约状态。
- 初始与结束前健康检查均验证 API/UI 200、MySQL 可连接、Redis PING、Qdrant readiness 200。8000 当时被无关桌面服务占用，因此本轮 FastAPI 在 8001，Vite 仍为 5173；只通过 `VITE_API_PROXY_TARGET` 将前端转发到 8001。停止脚本仅按 `qa_joint` PID 文件停止本轮服务，没有操作 8000。

## 问题与处理记录

| 场景 | 角色 | 实际与预期 | 根因 | 修复与复测 |
|---|---|---|---|---|
| E10 伪造 Origin 首次尝试 | 普通用户 | 通过浏览器路由篡改请求头时实际为 201，测试原本预期 403 | `frontend/vite.config.ts:14-16` 的 Vite 代理启用了 `changeOrigin`，会把 Origin 改写为可信后端源；该次结果不能证明后端接受了恶意 Origin。后端校验位于 `backend/app/auth/csrf.py:73-77,100-104`。首次写入仅发生在隔离测试租户，之后在重新造数时清理；最终两个测试租户也再次清理。 | `qa_joint/steps/system-errors.spec.cjs:125-149` 改为从独立浏览器上下文直接向真实 FastAPI 发送带伪造 Origin、有效 CSRF 的请求。复测返回 403 / `CSRF_ORIGIN_INVALID`，数据库行数为 0；新截图为 `09-write-protection/E10-02_user_forged_origin_rejected_err.png`。无产品代码修复。 |
| E8 恢复测试耗时 | 测试工具 | 首次全量回归结果通过，但单项耗时 4.2 分钟 | `execFileSync` 默认捕获子进程输出时，PowerShell 启动的服务进程导致父子进程输出句柄迟迟未关闭；这是结合 240 秒等待上限和耗时变化得出的根因判断。 | 在 `qa_joint/steps/system-errors.spec.cjs:18-26` 将 PowerShell 子进程的 stdio 设为 `ignore`；同一 E8 测试重跑 20 秒通过，仍验证双端 502 与恢复后的 200。截图时间已更新。 |

## 范围说明

可选的 S9 候补递补未执行；必需的 S0–S8、E1–E10 均已覆盖。没有修改 Alembic migration。最终执行 `cleanup.ps1` 后，测试租户数据和 `.runtime/fixtures.json` 已清理；执行 `stop.ps1` 后，8001、5173 均无监听，`qa_joint` PID 文件为 0 个。
