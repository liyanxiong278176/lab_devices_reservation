# 总体架构说明

本平台是面向高校实验室的自然日设备预约与管控系统，采用单体异步架构。后端只保留 Python FastAPI，前端使用 Vue 3 + TypeScript；MySQL 保存业务事实，Redis 提供缓存、辅助锁和限流，OutboxWorker 在同一 FastAPI 进程中执行可恢复异步任务。

![总体架构](drawings/01-architecture.png)

## 分层职责与技术栈

| 层次 | 职责 | 技术选型 |
|------|------|----------|
| 前端表现层 | SPA、路由、状态、图表、通知和表单 | Vue 3、Vue Router、Pinia、Element Plus、ECharts、Axios、TypeScript |
| 接入层 | 静态资源、REST/SSE/WebSocket 反向代理 | Nginx |
| 应用层 | 鉴权、学院隔离、预约状态机、报修、设备生命周期、缓存和异步任务 | Python 3.13、FastAPI、SQLAlchemy Async、Pydantic |
| 基础设施层 | 事务、缓存、可靠任务、实时提示 | MySQL 8、Redis 7、Alembic、持久化 Outbox、原生 WebSocket |

预约、审批、负责人交接、用户归还、负责人验收和设备状态变化集中在 `backend/app/application`，Controller 只负责参数校验和调用应用服务。数据库迁移统一由 `backend/migrations` 的 Alembic revision 管理。

## 自然日预约链路

浏览器按设备资源池和自然日查询可用量时，服务端汇总池内各实物设备的 MySQL 可预约状态，返回每天可预约的台数。Redis 另维护名额预检 Hash：key 为 `reserve:quota:{pool_id}:{date}`，field 为实物设备 ID，值 `1` 表示可用、`0` 表示不可用或已被并发请求预占。

提交 `POST /api/v2/reservations` 时，客户端为一次逻辑申请生成固定 `Idempotency-Key`，自动重试和恢复都复用同一 token 与相同请求内容。服务端先查询 MySQL 幂等结果；Redis 正常且无已知结果时，Lua 在所有请求日期对应的 Hash 中原子寻找同一批满足数量的实物设备并预占。辅助 String key 以该请求 token 跟踪 `HELD`、`COMMITTED`、`REFUNDED` 或 `UNKNOWN`，不放入名额 Hash；同 token 的 `HELD` 请求返回处理中，已终态则回 MySQL 取结果。MySQL 复核发现 Redis 预占设备已不可用时，会尝试从资源池其他实物设备重新分配；分配集合与预占集合不同时，先失效受影响日期缓存并写入 Outbox 重建任务。每日总量足够但跨日没有足够的共同设备时，整笔请求返回 `409 RESERVATION_DEVICE_NOT_CONTINUOUS`；某日名额不足时返回 `409 RESERVATION_QUOTA_INSUFFICIENT`。Redis 未就绪、Hash 未命中或 Redis 不可用时跳过 Redis，直接走 MySQL 分配路径；重建完成前不启用 Redis 预约缓存。

MySQL 是最终事实源。一个事务先以 `(user_id, Idempotency-Key)` 唯一键认领请求，再锁定候选实物设备行（`FOR UPDATE SKIP LOCKED`），复核设备可预约状态、维修/停用状态和整个日期范围的占用情况，最后写入预约主记录与每日明细。一次申请涉及的设备和日期全部在同一事务中提交；任何一天找不到同一批 N 台设备就整笔失败，不会部分成功。`v2_reservation_day(device_id, date)` 唯一约束最终防止同一设备同一天重复占用。这里采用候选实物设备行锁，不增加资源池/日期的聚合版本计数行：多日申请还必须绑定跨全部日期相同的实物设备集合。

幂等表保存规范化请求摘要和最终 HTTP 响应。同一用户以相同 token、相同内容重试时返回原成功或终态失败；相同 token 携带不同内容时拒绝。并发中的同 token 请求返回 `REQUEST_IN_PROGRESS`。明确失败通过事务保存为终态；预约写入与响应结果一并提交，避免只回滚预约却丢失失败幂等结果。Redis 预占成功但 MySQL 明确失败时，补偿 Lua 只处理辅助状态仍为本请求 `HELD` 的操作，再标记 `REFUNDED`；普通回滚释放预占设备，MySQL 判断缓存库存冲突时则删除受影响日期缓存并由 Outbox 重建，不能把实际已占用设备改为可用。MySQL 提交结果不明时标记 `UNKNOWN`，不盲目释放，通过原 token 查 MySQL 确认。

Redis 状态更新或补偿失败不改变 MySQL 结果。取消预约以 MySQL 条件更新和事务提交为准，并在同一事务写持久化 Outbox 任务；Worker 幂等重试同步 Redis。Redis 宕机或重建期间预约只走 MySQL，完整按 MySQL 重建所有相关日期 Hash 并确认就绪后才重新启用 Redis；周期对账继续用于修复后续缓存漂移。前端按当前用户和请求 token 将待确认请求内容存于 `localStorage`，通过 `storage` 事件通知其他标签页；收到终态结果后清除。浏览器存储仅负责恢复请求，预约状态仍以 MySQL 为准。

客户端对连接中断、临时服务/网关故障和 `REQUEST_IN_PROGRESS` 使用相同 token 与请求内容最多发送 3 次（首次加 2 次重试），采用退避并加入少量随机抖动。名额不足、跨日设备不连续、校验和权限错误不自动重试。达到重试上限仍无最终结果时保留原请求内容和 token，并以相同请求重放取得最终结果；确认成功或终态失败后才能创建新请求。`REFUNDED` 对同一 token 是终态；需要再次预约时生成新的 token。

预约记录只使用 `start_date`、`end_date` 和日期明细。用户不选择时分秒；交接、归还和验收时间只用于履约审计。所有预约均须负责人交接后才能进入使用中，用户在结束日提交归还后由负责人验收；异常设备自动进入维护状态。连续预约首日交接、结束日验收，重复预约的每个日期独立履约。

## 异步通知与实时提示

业务事务先写入 Outbox，再由同进程 Worker 使用租约、`SKIP LOCKED`、幂等任务键和退避重试生成通知记录。通知表是历史事实源，原生 WebSocket 只向在线用户推送低延迟提示；客户端断线或刷新后仍通过通知接口补齐历史和未读数。

## 学院隔离

学院是租户边界。普通用户的设备、预约、报修和通知都按当前数据库用户学院过滤；实验室负责人只能管理自己负责的实验室或学院；系统管理员才允许跨学院。权限校验在服务端应用服务中完成，前端菜单隐藏不承担安全职责。

## 容器化

生产环境使用 `docker-compose.prod.yml`，包含 MySQL、Redis、Qdrant、FastAPI app 和前端 Nginx。生产密码和 JWT secret 必须由环境变量提供，缺失或使用默认值时 FastAPI 拒绝启动。部署细节见根目录 `DEPLOY-WITH-WEBHOOK.md`。

## 答辩要点

- 只维护一套 Python 后端，避免双语言双状态机造成的实现漂移。
- 预约正确性由 MySQL 候选设备行锁、自然日唯一约束和请求幂等记录兜底；Redis 只负责预占和降低冲突，故障或重建期间预约回退到 MySQL。
- Outbox 让通知、爽约扣分和候补递补在重启后可恢复。
- 条件更新和学院范围校验防止重复状态变更与跨学院越权。
- 预约、现场交接、用户归还和负责人验收都保留可追溯业务记录，方便异常处理和审计。
