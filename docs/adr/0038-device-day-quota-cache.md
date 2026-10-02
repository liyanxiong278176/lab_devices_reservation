# ADR-0038：资源池预约名额按实物设备和自然日缓存

设备资源池的多日预约必须由同一批实物设备覆盖整个日期范围，因此 Redis 以 `reserve:quota:{pool_id}:{date}` 保存 Hash，field 是实物设备 ID，值 `1/0` 表示该设备当天可用/不可用或已被预占；Lua 原子地选择并预占所有日期共有的 N 台设备。每次预占另有 String 操作标记 `reserve:quota:{pool_id}:op:hold:{token}`，状态从 `HELD` 转为 `COMMITTED`、`REFUNDED` 或 `UNKNOWN`；它用于跟踪跨服务流程，不属于设备名额 Hash。

MySQL 事务及 `(device_id, date)` 唯一约束仍是最终防超约依据。MySQL 提交成功后，Redis 把标记转为 `COMMITTED`；确认回滚后，补偿 Lua 归还名额并把标记转为 `REFUNDED`。提交结果不确定时不归还名额，而是把标记转为 `UNKNOWN` 并删除相关名额 Hash，强制后续请求回源 MySQL。Redis 与 MySQL 不共享事务，标记更新或补偿失败时由名额对账任务按 MySQL 重建缓存；缓存未命中或 Redis 不可用时回退到 MySQL。

当每个日期单独的可用量都达到申请数量、但跨日共同可用的实物设备不足时，整笔预约失败并返回 `409 RESERVATION_DEVICE_NOT_CONTINUOUS`；单日可用量不足时返回 `409 RESERVATION_QUOTA_INSUFFICIENT`。缓存短暂低估时可能提前拒绝请求，MySQL 对账会重建缓存状态。
