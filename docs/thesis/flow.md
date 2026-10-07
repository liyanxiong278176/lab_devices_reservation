# 核心业务流程

本系统的核心链路是“创建预约 → 审批 → 负责人交接 → 使用中 → 用户归还 → 负责人验收”。预约时间采用自然日，
一天就是一个占用单元，不再拆分小时、分钟或 15 分钟槽位。

## 状态机

```text
PENDING ──审批通过──> APPROVED ──首日负责人交接──> IN_USE ──用户归还──> RETURN_PENDING ──负责人验收──> COMPLETED
   │                       │                         │
   ├─用户取消──> CANCELLED  ├─驳回──> REJECTED       └─违规──> VIOLATED
   │                       └─预约首日未交接──> NO_SHOW
```

状态转换集中在 `backend/app/application/reservations.py` 的
`ReservationService`，Controller 只负责参数接收。每个有效设备日都写入
`v2_reservation_day`，并由 `(device_id, date)` 唯一约束兜底防止并发超约。

## 主流程

1. 普通用户只能读取所属学院的设备，提交 `device_id`、`start_date`、`end_date` 和用途。
2. 创建前检查设备状态、不可预约日期、现有占用、个人有效预约上限和信用限制。
3. 需要审批的设备进入 `PENDING`；免审批设备直接进入 `APPROVED`。
4. 负责人只能审批自己管理的实验室或学院设备。审批成功后，预约进入待交接队列并写入超时任务；预约首日结束仍未完成交接时，后台任务幂等地转为 `NO_SHOW`，释放全部日期并扣除信用分。
5. 所有设备都由负责人在预约首日现场交接，交接完成后预约进入 `IN_USE`。用户只能在预约结束日提交归还；预约进入 `RETURN_PENDING`，负责人验收后才进入 `COMPLETED`。正常验收恢复为空闲，损坏/丢失或仍有未完成报修则保持 `MAINTENANCE`。
6. 取消、驳回、违规和爽约都会释放日期，并创建候补提升任务。候补用户收到通知后需
   重新提交预约，系统不会绕过正常审批、交接和冲突校验。
7. `COMPLETED` 预约的本人可以提交一次 1~5 星评价和备注；负责人只能查看自己负责范围内
   的评价，评价写入审计记录，作为后续设备服务质量统计的事实来源。

## 并发与异步

- MySQL 事务使用 `FOR UPDATE SKIP LOCKED` 锁定候选实物设备行，复核设备状态及所有请求日期，再整体写入预约；`UNIQUE(device_id, date)` 是最后防线。多日多台申请必须绑定覆盖整个日期范围的同一批设备，任一天不足就整笔回滚。
- Redis 每资源池/日期使用设备 ID 到 `1/0` 的 Hash。Lua 脚本原子预占跨日期共有的设备，独立辅助 key 以客户端请求 token 记录 `HELD`、`COMMITTED`、`REFUNDED` 或 `UNKNOWN`。Redis 只做快速拦截；不可用、缓存未就绪或恢复重建期间直接走 MySQL。
- 幂等记录使用 `(user_id, request_token)` 唯一键并保存请求摘要和最终响应。同 token 同内容返回原结果，不同内容拒绝；并发处理返回 `REQUEST_IN_PROGRESS`。客户端最多请求 3 次，临时故障与处理中响应使用同一 token 退避重试；次数用尽后继续恢复原请求，确认终态后才可创建新请求。浏览器用按用户和 token 隔离的 `localStorage` 跨标签页恢复请求，并通过 `storage` 事件同步状态。
- MySQL 明确失败的幂等结果持久化后才将 Redis 预占标记为 `REFUNDED`；普通补偿 Lua 只释放仍由该 token 持有的 `HELD` 设备日期。若 MySQL 发现缓存预占库存与数据库冲突，则失效相关日期缓存并由 Outbox 按 MySQL 重建，不能把数据库已占用的设备恢复为可用。`REFUNDED` 对同 token 是终态，需要重新预约时使用新 token。提交结果不确定时不补偿，按原 token 重放查询 MySQL。取消以 MySQL 事务为准，并在事务中写 Outbox；Worker 幂等同步 Redis，失败时可从 MySQL 全量重建，过程中不启用 Redis 预约缓存。
- 业务事务提交后写入同库 Outbox，单 FastAPI 服务内的异步 Worker 负责通知、超时和候补
  任务。任务带唯一键、重试次数和状态，重复执行不会重复写通知。
- WebSocket 只做实时提示，通知表才是事实来源；断线重连后前端重新拉取历史和未读数。

## 权限边界

系统管理员可跨学院管理；普通用户和实验室负责人都受 `college_id` 约束。负责人进一步
通过 `Lab.manager_id` 或 `College.manager_id` 限定设备、审批、报修和不可预约日期的管理范围。
