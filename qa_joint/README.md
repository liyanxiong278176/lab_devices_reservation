# 双角色前后端联调

> 历史验收资料：本目录记录 Spring Boot 迁移前的 Python/FastAPI 实验。下方旧启动命令不适用于当前版本；当前运行入口和标准浏览器测试以根目录 README、`backend-java/` 与 `frontend/e2e/` 为准。旧截图与浏览器会话不入库。

本目录是独立于 `frontend/e2e` 的真实浏览器联调套件。测试使用真实 FastAPI、Vue、MySQL、Redis 与独立浏览器上下文；每个重要操作保存步骤前和结果后的截图。

本机的 `8000` 端口由桌面沙箱服务占用。本次联调把真实 FastAPI 放在 `8001`，并通过现有 `VITE_API_PROXY_TARGET` 让真实 Vite 前端转发到它；不会停止无关的 8000 端口进程。

## 运行

```powershell
docker-compose up -d mysql redis qdrant
cd backend
uv sync
uv run alembic upgrade head
cd ..\frontend
pnpm install
cd ..
.\qa_joint\scripts\start.ps1
.\qa_joint\scripts\seed.ps1
$env:QA_JOINT_PASSWORD = 'E2e-123456'
pnpm --dir frontend exec playwright test --config=..\qa_joint\pw.config.ts
```

完成后运行 `qa_joint\scripts\cleanup.ps1` 清理 `e2e-joint01` 与 `e2e-joint02` 测试租户；最后运行 `qa_joint\scripts\stop.ps1` 停止本目录启动的前后端进程。脚本拒绝覆盖已存在的测试学院。

运行产物保存在 `screenshots/` 与 `results/`。运行时 PID、账号索引及敏感会话材料不得写入报告。

## 前端人工复看

本轮结束后会保留 `qa_joint` 启动的前后端服务，并重新播种一份干净的测试学院，便于直接登录查看。前端入口为 `http://127.0.0.1:5173/login`，真实 FastAPI 运行在 `http://127.0.0.1:8001`。测试账号密码统一为 `E2e-123456`。

| 账号 | 角色 | 学院 |
|---|---|---|
| `e2e-joint01-user` | 普通用户 A | `e2e-joint01` |
| `e2e-joint01-user2` | 普通用户 B | `e2e-joint01` |
| `e2e-joint01-admin` | 系统管理员 | 跨学院 |
| `e2e-joint01-manager` | 实验室负责人 | `e2e-joint01` |
| `e2e-joint02-user` | 外学院普通用户 | `e2e-joint02` |

建议用两个浏览器配置文件或普通窗口与无痕窗口分别登录普通用户和管理员，避免 Cookie 会话互相覆盖。

### 普通预约到归还验收

1. 用 `e2e-joint01-user` 登录，打开“设备”，进入设备详情后选择“预约”。自然日预约选择同一天作为起止日期，可在当天完成全部履约；选择未来日期则要等到预约首日签到、结束日归还。
2. 填写用途并提交。在“我的预约”检查状态为“待审批”。
3. 在另一浏览器用 `e2e-joint01-admin` 登录，打开“待审批”，找到刚才的预约并点击“通过”。回到用户窗口检查预约状态和“我的通知”里的实时审批通知。
4. 管理员打开“设备交接”，找到预约并完成交接。用户刷新“我的预约”，状态应为“使用中”。
5. 用户在预约结束日打开预约并提交归还；管理员在“设备交接”的“待验收”列表核对照片并确认验收。用户预约最终应为“已完成”。
6. 用户可以在预约详情提交使用评价。另选第二台测试设备，在“提交报修”填写故障；管理员到“报修处理”先“受理”再“解决”，用户最后在“我的报修”确认维修结果。

### 两个普通用户同时抢约

1. 分别登录 `e2e-joint01-user` 和 `e2e-joint01-user2`，选择同一台尚未被占用的设备和同一个可预约自然日（测试日期范围为未来 8 天内）。
2. 两个页面都填写用途并准备提交，随后尽量同时点击“提交预约”。预期一边成功，另一边显示明确冲突；刷新管理员“待审批”，该设备日期只能有一条申请。

### 学院隔离与 Redis 故障

- 用 `e2e-joint02-user` 登录可查看另一学院的设备；回到 `e2e-joint01` 普通用户会话访问管理页面或外学院预约详情，应被拒绝。
- 如需手工复看 Redis 故障，在 PowerShell 执行 `docker-compose stop redis`，刷新普通用户和管理员的数据页，应在页面右上角看到“登录服务暂时不可用，请稍后重试”；随后执行 `docker-compose start redis`，等待服务恢复并重新登录/刷新。不要只执行停止命令而遗漏启动命令。

关键截图见 `screenshots/01-normal/`（完整业务流）、`screenshots/05-concurrency/`（双用户竞争）和 `screenshots/10-redis-outage/`（Redis 停机/恢复）；逐步索引见 `results/SCREENSHOT_LEDGER.md`。
