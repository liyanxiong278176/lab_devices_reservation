# 数据模型设计

当前后端使用 SQLAlchemy 2 + Alembic，主库为 MySQL 8。迁移脚本位于
`backend/migrations/versions/`，最新业务增强从 `0011` 到 `0013`，不修改已经执行过的
历史迁移。

## 核心表

| 表 | 作用 | 关键约束/索引 |
|---|---|---|
| `sys_user` | 用户、学院归属、信用状态 | `username` 唯一，`college_id`、`status` 索引 |
| `college` / `lab` | 学院和实验室管理范围 | 负责人字段约束管理边界 |
| `device` | 设备目录和生命周期状态 | `college_id + status + id`、`college_id + lab_id + id` |
| `reservation` | 预约主记录和状态机 | `user_id + id`、`college_id + status + id` |
| `v2_reservation_day` | 每个设备每天一条占用记录 | `UNIQUE(device_id, date)`，并发防超约最终兜底 |
| `v2_idempotency_key` | 每个用户的请求 token、规范化请求摘要和最终响应 | `UNIQUE(user_id, key)`；同键同内容重放原结果，同键不同内容拒绝 |
| `v2_reservation_inspection` | 归还验收记录 | `reservation_id` 唯一 |
| `v2_reservation_waitlist` | 设备日期候补队列 | 设备、日期、用户唯一，按自增 id 排队 |
| `v2_reservation_blackout` | 学院/实验室/设备不可预约日 | 作用域、日期唯一 |
| `v2_credit_event` | 爽约/违规信用变更 | 用户、时间索引 |
| `v2_repair_report` | 报修工单 | 学院、状态、创建时间索引 |
| `v2_device_status_history` | 设备状态生命周期 | 设备、时间索引 |
| `notification` | 站内通知事实表 | 用户、已读、id 联合索引 |
| `v2_outbox_task` | 通知、超时、候补可靠任务 | 状态、执行时间、聚合键索引；任务键唯一 |
| `v2_refresh_session` | 可撤销、可轮换刷新会话 | token id 唯一，用户活跃会话索引 |
| `v2_upload_asset` | 校验后的私有图片附件 | 随机 token 唯一，按用户/学院隔离 |
| `v2_reservation_feedback` | 完成预约后的设备满意度评价 | 每个预约最多一条，按设备/学院索引 |
| `v2_audit_log` | 预约、设备、报修、用户审计 | 作用域和目标索引 |

## 预约数据完整性

预约输入只有 `date`，`start_time/end_time` 仅作为旧数据兼容字段写入全天边界，不参与
冲突判断。提交时 MySQL 事务使用 `FOR UPDATE SKIP LOCKED` 选择并复核候选设备，再写入
`v2_reservation_day`；`UNIQUE(device_id, date)` 保证同一实物设备同一天最多有一个占用项。
多台多日申请必须找到覆盖全部日期的相同设备集合，并在单一事务中全成或全回滚。

请求幂等表以 `(user_id, key)` 唯一约束串行化相同 token 的请求，并保存请求摘要与最终
响应；token 相同但摘要不同时拒绝。Redis Lua 只作快速预占和辅助请求状态跟踪，Redis
不可用或完整重建未完成时回退到 MySQL。预约及取消的事实以 MySQL 为准，取消后的 Redis
同步通过同事务 Outbox 幂等重试。

## 数据权限

除系统管理员外，查询必须带当前用户的学院条件；负责人查询额外连接实验室/学院负责人
条件。所有写操作再次在 Service 中校验归属，不能依赖前端隐藏菜单。附件读取也按学院
校验，不能通过猜测文件名跨学院访问。

## 生命周期和历史

设备进入维修、停用、离线或退役状态后不会出现在可预约集合；状态变化写入历史表。
报修解决只有在先受理后才能完成，设备仍存在其他未完成报修时不会被错误恢复为空闲。
预约的归还验收、信用事件、审计和通知都与主业务事务一起提交，便于答辩和生产排查。
