# ADR-0040：预约采用设备行锁、固定请求 token 与可恢复 Redis 预占

## 状态

已接受

## 背景

预约最小冲突单位是实物设备与自然日。资源池中的多台设备可并行预约；一次申请多台并跨多个自然日时，必须绑定覆盖整个日期范围的同一批实物设备，且整笔申请全成或全回滚。设备维修、停用或已有有效预约时不可被分配。

旧预约协调决策分别记录在 ADR-0021、ADR-0035 和 ADR-0038：使用 Redis 设备日期锁、看门狗租约和设备日名额预占。现需明确数据库分配锁、请求幂等、失败补偿、客户端超时重试及 Redis 恢复期间的行为。

## 决策

### MySQL 负责最终预约正确性

1. MySQL 是预约事实源。创建预约时，事务先认领 `(user_id, request_token)` 幂等键并校验请求摘要，再以 `SELECT ... FOR UPDATE SKIP LOCKED` 选择候选实物设备，锁定后复核设备当前状态、维修/停用状态和完整日期范围的占用情况。
2. 一次申请涉及的预约主记录和所有 `(device_id, date)` 占用明细在同一事务中写入。多日申请只有在找到同一批 N 台设备覆盖全部日期时才成功；无法找到时整笔失败，不允许部分成功。
3. `v2_reservation_day` 的 `UNIQUE(device_id, date)` 是最终防止同一设备同一天重复占用的约束。取消、驳回、爽约、违规或完成等释放路径按现有模型在事务中释放占用明细。
4. 采用候选实物设备行的悲观锁，不另建资源池/日期聚合数量版本行。版本号乐观锁适合对单条库存计数记录做条件竞争更新；本预约还要求跨日期绑定同一批实物设备，聚合数量版本本身无法保证设备集合连续性。`SKIP LOCKED` 使并发事务可选择其他空闲设备，唯一约束继续兜底。

### Redis 仅作快速预占和缓存

- Redis 以 `reserve:quota:{pool_id}:{date}` 存储 Hash，field 为实物设备 ID，`1` 表示缓存中可用，`0` 表示不可用或已预占。Lua 在一笔请求涉及的全部日期中原子寻找相同的 N 台设备并预占。
- 每笔操作另有 String 辅助 key，例如 `reserve:quota:{pool_id}:op:hold:{user_id}:{request_token}`。它复用客户端固定 token，只表示请求处理状态：`HELD`、`COMMITTED`、`REFUNDED` 或 `UNKNOWN`，不代表预约业务生命周期。相关 Redis key 使用相同资源池 hash tag，以便 Lua 在 Redis Cluster 中原子操作。
- Redis Lua 可以提前拒绝缓存中已满或跨日共同设备不足的请求；预占成功后仍必须经过 MySQL 事务。Redis 缺 key、不可用或正在恢复时，预约直接走 MySQL。
- 如果 Redis 预占的设备被 MySQL 复核为不可用，MySQL 会放宽到资源池其余设备重新分配；若最终分配与预占集合不同，提交前删除该资源池相关日期的缓存并写入同事务 Outbox 重建任务，避免把缓存选中的旧设备误认为真实预约设备。
- Redis 宕机后先停用预约缓存。使用 MySQL 重建全部相关日期的设备状态，确认重建完成后才重新启用 Redis；周期对账继续修复后续漂移。

### 固定 token 的幂等和重试

- 客户端为一次逻辑预约生成固定 token，并在首次请求、自动重试、页面恢复和跨标签页恢复中复用。服务端先查 MySQL 幂等结果，再检查同 token 是否已有 Redis `HELD` 标记，然后在 MySQL 事务内创建未提交的幂等认领；Redis 可用且缓存已就绪时执行 Lua 预占，之后在同一 MySQL 事务中写预约和最终响应。Redis 不可用或未就绪时跳过预占，直接走 MySQL。MySQL 使用现有 `v2_idempotency_key` 的唯一键 `(user_id, key)`，存储规范化请求摘要和最终响应，不新增幂等表。
- 同一用户、相同 token、相同请求内容返回原成功或终态失败；同一 token 的请求内容不同则拒绝。并发请求遇到尚未结束的相同 token 时返回 `REQUEST_IN_PROGRESS`；MySQL 唯一键争用的锁等待超时也映射为处理中。
- 幂等凭证与预约写入在同一 MySQL 事务内处理。确定的业务失败也将最终失败响应持久化；必要时通过保存点回滚预约写入、保留幂等行并提交失败响应。MySQL 提交结果不确定时不能伪造终态失败。
- 客户端总请求次数最多为 3 次（首次请求加 2 次重试），仅对网络断连/超时、临时服务或网关故障，以及 `REQUEST_IN_PROGRESS` 退避重试；名额不足、设备不连续、校验和权限错误不自动重试。超过次数仍无最终结果时保留原请求和 token，用完全相同的请求重放以获得已存响应或处理中状态；只有确认成功或终态失败后才能开始新的逻辑请求。
- 待确认的请求内容和 token 以用户及 token 为键存入 `localStorage`，支持同源标签页读取；通过 `storage` 事件通知其他标签页更新状态。只在最终成功或终态失败后清除，登出时清理当前用户的待确认请求。未确认请求不按时间自动清除，避免丢失原 token 后把重放误当新申请。浏览器存储只是恢复手段，不是预约事实源。

### Redis 补偿、未知结果与取消

1. MySQL 成功提交后，将 Redis 标记由 `HELD` 转为 `COMMITTED`，对应设备日期继续保持不可用。若标记提交失败，按 token 查 MySQL并由对账修复缓存。
2. MySQL 明确失败且终态失败结果已持久化后，补偿 Lua 仅在该 token 标记仍为 `HELD` 时处理并将标记改为 `REFUNDED`。普通回滚会释放该请求预占的设备日期；若 MySQL 失败表明缓存库存与数据库冲突，则 Lua 删除受影响日期的 Hash/就绪标记，由 Outbox 从 MySQL 重建，不能把实际已占用设备直接改回可用。`REFUNDED` 对该 token 是终态，同 token 重放数据库中的失败结果，不重新预约；新逻辑预约必须生成新 token；重复补偿必须幂等。
3. MySQL 提交结果不确定时不释放 Redis 预占。尽力将标记置为 `UNKNOWN`，按原 token 查询 MySQL；确认结果前客户端保留原请求。若 Redis 不可用或缓存状态不可靠，按 MySQL 重建，不反向以 Redis 修正 MySQL。
4. 取消以 MySQL 条件更新和事务提交为准。取消事务同时写持久化 Outbox 任务；单体服务中的 Worker 幂等重试 Redis 同步，持续失败时可由 MySQL 全量重建修复，不引入 MQ。

## 后果

- 不同设备仍可并发预约；竞争同一设备的事务由 MySQL 行锁协调，唯一约束阻止最终重复占用。
- Redis 故障会降低预检性能，但不会改变预约正确性；恢复重建期间短暂回退到 MySQL。
- Redis 预占与 MySQL 提交不能组成跨服务原子事务，故系统通过请求 token、终态响应持久化、条件补偿和 MySQL 对账提供幂等及最终修复。
- 相比只使用 `sessionStorage`，`localStorage` 支持同源多个标签页恢复同一请求；其内容按用户/token 隔离，并在最终结果确认或登出时清理。跨设备恢复不由浏览器存储提供。

## 取代范围

本 ADR 中的 MySQL 候选设备锁选择取代 ADR-0021 与 ADR-0035 对预约正确性协调锁的选择；本 ADR 补充并优先于 ADR-0038 中 Redis 预占 token 生命周期、终态失败幂等、请求重试与故障恢复的定义。ADR-0038 中按实物设备和自然日组织 Redis Hash、Lua 选择跨日期同一批设备的定义继续适用。

## 参考

- [MySQL 8.0 InnoDB Locking Reads](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-reads.html)
- [MDN: `sessionStorage`](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage?lang=en-US)（按标签页隔离）；跨标签页恢复采用同源共享的 `localStorage`。
