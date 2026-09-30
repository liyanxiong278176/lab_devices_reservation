# 后端 + AI 一体化评测报告

评测日期：2026-09-30。结果来自本机一次性 QA schema、独立 Redis DB 和独立 Qdrant collection；真实模型调用关闭，使用本地确定性 OpenAI-compatible mock。项目 `.env` 未修改，报告不含账号、密码、令牌或连接凭据。

## 结论

覆盖了后端功能与权限、MySQL 预约并发、预约全生命周期、AI 写操作确认、前端页面隔离、离线 AI 指标，以及 1k/10k/100k 设备列表分页负载。QA 后端/AI/集成测试 28 项通过，前端单测 353 项通过，浏览器 E2E 4 项检查通过，后端与 QA Python lint 均通过。

**高并发档观察到服务拒绝请求。** 单账号 burst 在默认令牌桶耗尽后返回 429；关闭限流的 Locust 容量档在 25 用户第三轮出现 2 个 503，在 50/100 用户档出现明显 503，并伴随部分登录失败后的 401。该表现是当前本机单实例配置的过载边界，详见负载结果；它不能代表生产容量。

## 执行结果

| 领域 | 结果 | 证据与范围 |
|---|---|---|
| 后端 + AI + 集成 | **28 passed** | `qa_system/backend_tests`、`ai_tests`、`integration`，41.02 秒；没有导入或调用项目现有后端测试辅助代码 |
| 前端单测 | **353 passed / 65 files** | `pnpm test` |
| 浏览器 E2E | **通过** | 普通用户菜单权限、本学院设备可见/跨学院设备隐藏、页面 AI 只读预约查询、负责人待审批入口 |
| Python lint | **通过** | `uv run ruff check .`（backend）；QA 脚本另跑 Ruff 并通过 |
| 前端生产构建 | **通过** | `pnpm build`；构建输出含超过 500 kB 的 chunk 提示及依赖中的 `#__PURE__` 注释告警，均未阻止构建 |
| AI golden / holdout | **各 8 项指标均为 1.0** | 离线手工 fixture，仅验证指标管线、证据匹配与隔离断言；不能推断真实知识库或真实模型质量 |
| API 能力盘点 | **142 routes / 7 AI tools / 132 settings** | 配置只导出名称和类型，未导出配置值 |

### 功能、安全与 AI×后端链路

- 同设备、同自然日两路真实 MySQL 并发请求得到一个 201、一个 409，数据库冲突记录只有一条；重复幂等键返回同一预约。
- 实际 API 状态链通过 `PENDING → APPROVED → IN_USE → COMPLETED`；重复审批和重复归还按预期返回 409。
- AI 创建预约经 SSE 返回待确认预览；确认前数据库没有新增预约，明确确认后只新增一条，重放确认返回已处理且无重复写入。
- 浏览器中普通用户只看见本学院设备且菜单不含审批；负责人页面可以进入待审批列表。AI 页面完成只读“我的预约”查询。
- Redis 不可用的隔离探测中，`/devices` 与 `/ai/status` 返回 503，认证依赖失败关闭。
- 评测复现了 AI 证据草稿可把注入指令中的 canary 内容显示为来源声明的问题。已在 [output_validation.py](../../backend/app/ai/output_validation.py) 增加指令/canary claim 拒绝规则，并在 [test_ai_security_contracts.py](../ai_tests/test_ai_security_contracts.py) 增加回归用例。

浏览器截图：

- [普通用户设备学院隔离](playwright/student-device-tenant-scope.png)
- [页面 AI 只读查询](playwright/student-ai-business-query.png)
- [负责人审批菜单](playwright/manager-approval-scope.png)

### AI 离线评测

Golden 与 holdout 的 contextual precision/recall/relevancy、faithfulness、answer relevancy、factual correctness、citation validity、tenant citation isolation 均达阈值，fixture 得分均为 1.0。数据明确标记 `offline_fixture_only: true`；测试没有连接外部模型，当前外部推理费用为 0。应用内部 token/quota 计费的生产单价和真实供应商成本未评估。

### 性能与数据规模

- 单账号混合只读 API（设备、本人预约、通知、AI 状态/会话）在并发 5 档三轮各 100 请求均成功；并发 10 前两轮全成功，第三轮出现 33 个 429。25/50/100 的大量 429 是同一 principal/IP 的默认限流触发，不能当作数据库吞吐量。
- Locust 使用真实 CSRF 登录与混合只读业务/AI API。容量档仅在隔离 API 中关闭限流；每档 10 秒、5/10/25/50/100 用户各三轮。25 用户前两轮无失败，第三轮 2 个 503；50 用户三轮失败数为 22、36、528；100 用户三轮失败数为 102、100、114。高档错误包含服务返回的 503，以及部分登录被拒后后续受保护请求的 401。5/10 用户档三轮均无失败。
- `device` 表新增 1k、10k、100k 三个独立 QA cohort，分别测本学院列表浅页与接近 100k 跳过量的深页，各三次不同页。100k cohort 批量插入用时 4.72 秒；设备列表浅页 p50/max 131.53/131.62 ms，深页 p50/max 211.00/241.37 ms。Redis 页面缓存保持启用。
- 上述性能结果来自本机 Windows 单进程 API、容器 MySQL/Redis，数据仅为设备目录；不是生产容量承诺，也没有把 100k 行扩展到预约明细、通知或 Outbox 表。

完整明细见 [单账号限流曲线](performance-matrix.md)、[Locust 并发矩阵](locust-matrix.md) 和 [设备数据规模结果](database-scale-profile.md)。

## 尚未覆盖 / 需后续验证

- 未进行真实供应商模型的准确率、延迟、超时/重试、token 成本对比；没有任何真实凭据或供应商请求。
- Qdrant 真实知识文档的多租户检索、重建/回滚与 citation ACL 未形成端到端数据集；AI 指标仍是离线小型 fixture。
- Outbox 租约过期、`SKIP LOCKED` 抢占、指数退避、死信和多 worker 故障恢复未进行 MySQL/Redis 并发集成验收。
- 前端 E2E 覆盖了本轮代表性页面链路，未逐项覆盖报修、通知 SSE 重连、签到/归还 UI 和管理员所有菜单流程。
- 并发 25 起出现少量 503，50/100 档明显过载；需要结合目标部署规格评估 DB pool、Admission/queue 与登录峰值配置后，重新做容量验收。
- 项目说明中的 Alembic head 写为 `0034_notification_sequence`，实际迁移 head 为 `0036_knowledge_build_ordering`。本轮只在一次性 schema 上迁移到实际 head，没有修改任何迁移文件。

## 主要文件

- 独立 harness 说明：[README.md](../README.md)
- 测试依赖：[requirements.txt](../requirements.txt)
- API/AI 能力盘点：[endpoint-capability-inventory.md](endpoint-capability-inventory.md)
- 离线 AI 指标：[golden-metrics.json](golden-metrics.json)、[holdout-metrics.json](holdout-metrics.json)
- 性能数据：[performance-matrix.csv](performance-matrix.csv)、[locust-matrix.json](locust-matrix.json)、[database-scale-profile.csv](database-scale-profile.csv)

测试完成后已停止 QA API、mock provider 和 Vite，并清理本轮专用 schema、Redis DB、Qdrant collection、临时账号及私密 runtime manifest。结果文件和截图保留在 `qa_system/results/`。
