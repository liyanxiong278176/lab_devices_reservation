# 前端流程截图册

截图册是本地验收产物，目录位于 `.artifacts/browser-flow-日期/`，不提交截图、测试凭据或浏览器会话。根目录 README 链接指向最近一轮完整通过的截图册。

标准 `frontend/e2e/` 覆盖普通用户、负责人和系统管理员的预约审批、交接与归还验收、报修、管理页面、权限与学院隔离、并发预约及通知重连。处罚申诉、逾期和维护校准计划已经移除，不重新执行其旧脚本。设备维修状态和损坏归还报修仍需验证。

## 重新生成

先启动 Java API 与 Vue，使用独立测试 MySQL 和 Redis，并为数据工具配置 `LAB_MYSQL_DSN`、`LAB_REDIS_URL`、`LAB_ENVIRONMENT=test`。`E2E_API_URL`、`E2E_BACKEND_PORT`、`E2E_BASE_URL` 与 `VITE_API_PROXY_TARGET` 应指向这套测试服务；跨端口运行时，后端 `LAB_CORS_ORIGINS` 必须包含测试前端 Origin。

在 `frontend/` 执行以下命令，将目录日期换成本轮日期：

```powershell
$env:E2E_FLOW_CAPTURE='1'
$env:PLAYWRIGHT_JSON_OUTPUT_FILE=[System.IO.Path]::GetFullPath('../.artifacts/browser-flow-20261014/results.json')
pnpm test:e2e -- admin-control-plane.spec.ts full-chain.spec.ts tenant-isolation.spec.ts notification-reconnect.spec.ts csrf-multitab.spec.ts multi-user-admin-collaboration.spec.ts page-audit.spec.ts --output=../.artifacts/browser-flow-20261014/raw '--reporter=list,json'
node e2e/build-flow-gallery.mjs ../.artifacts/browser-flow-20261014
```

`flow-test.ts` 仅在 `E2E_FLOW_CAPTURE=1` 时对真实页面操作逐步截图；步骤日志不记录输入值。过程截图保持固定视口，避免截图动作改变弹窗/表格尺寸，最终核对截图可保留整页。普通 E2E 不额外截图。

生成器要求每个用例的最新验证结果均通过，并核对每条流程有截图；不将上传用的 1px 占位图片当作截图。`viewer/gallery.html` 可直接用浏览器打开，支持流程筛选、搜索、点击放大、方向键翻页和原图查看；`manifest.json` 记录实际数量，`REPORT.md` 提供流程索引。

修正用例后单独复跑时，将输出保存在同册的 `retest-raw/` 和 `retest-results.json`，生成命令末尾追加 `retest-results.json`。生成器按用例 ID 核对最新通过结果，只选最终通过版本的截图，保留原始测试报告而不改写失败结果。
