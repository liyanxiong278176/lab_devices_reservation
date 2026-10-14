> 历史实验记录：以下结果与脚本来自迁移前的 Python/FastAPI 版本，不代表当前 Spring Boot 版本的性能；当前运行与验收入口见根目录 README。

# 简历指标实测

在仓库根目录启动本地依赖：`docker-compose up -d mysql redis`。随后从 `backend/` 执行：

```powershell
uv run python benchmarks/run_resume_evidence.py --concurrency 1
```

脚本只接受本机 Compose MySQL，创建随机命名的 `lab_resume_*` 隔离库，并在该库执行当前 Alembic head；另启动独立临时 Redis 容器。根目录 `.env` 只用于加载现有连接配置，不会改写。测试端口为 8005、8006、8007、5175、6392，任何端口已经占用都会拒绝执行。退出时仅停止本次启动的进程，删除本次 Redis 容器、隔离库及其临时授权，不清理共享 Redis 或其他数据库。

## 100 条断线通知

执行标准 `frontend/e2e/notification-stream-live.spec.ts` 中的用例 2。浏览器先接收 A/B 两条通知，以实际 SSE 游标作为断线基准；代理中断连接并阻止重连。向本次隔离用户提交 100 条 Outbox 通知，等待 MySQL 保存全部 100 条后才恢复代理。

断言实际重连请求带原 `Last-Event-ID`，Chromium CDP 收到恰好 100 条 `notification` 帧，通知 ID、标题各有 100 个，序号连续递增，无丢失或重复。另断言 `batch-complete` 的补发数量为 100，前端显示批次同步提示，并逐页检查通知中心的全部 102 条记录；100 条离线通知各显示一次。这里“展示一次”指通知中心记录，批次补发仅弹一次摘要提示。

证据位于输出目录的 `notification/`，含浏览器抓包、逐页截图、补发摘要和测试报告。超过单次 SSE 的 100 条上限时依赖 HTTP 历史补偿，此场景不声称无限量 SSE 补发。

## 传统分页和延迟关联分页

隔离夹具固定为 100 台设备、10,000 条已完成预约，每页 20 条，共 500 页。两个专用 FastAPI 进程的数据库、索引、权限过滤、稳定排序、连接池、认证、总数计数、五组 ORM 关联加载和响应序列化保持一致，限流及后台 Worker 均关闭。

- 传统方案只在基准进程中替换 `ReservationService.list_mine`：完整行 SQL 按权限和筛选条件过滤、排序，之后 SQL `OFFSET/LIMIT`；没有把全量实体取到 Python。
- 延迟关联方案运行原生产方法：先在 ID 子查询中完成相同过滤、排序及分页，再 JOIN 加载本页完整记录。生产实现没有新增切换开关，也没有改动。

默认单并发，每次请求完成后再发下一次。每轮每种方案正式请求 1,000 次，500 页各读取两次，固定随机种子打乱顺序。正式计时前两种方案各按同样方式顺序预热全部 500 页，预热不计入统计。默认六轮，传统→延迟和延迟→传统交替，各占三轮，减少运行顺序偏差；也可通过 `--rounds` 指定轮数。逐页比较完整响应摘要，并补充状态及交接状态筛选的一致性检查。`--concurrency` 可用于复现历史并发负载，但不能把不同并发数的结果拼接成 A/B 对比。

`pagination-comparison.json` 保存每轮和汇总指标；默认汇总 P95 用每种方案六轮共 6,000 条客户端 HTTP 延迟样本计算最近秩分位数，包含认证与数据库读取链路，但不包含登录及预热。`pagination-samples.jsonl` 保留每次请求的页号、延迟、状态、响应摘要和起止单调时钟时间；单并发时可据此检查请求区间没有重叠。`pagination-rounds.jsonl` 实时保留每轮摘要；`database-evidence.json` 保存 MySQL 版本、实际迁移 head、索引以及第 500 页的两种 SQL 和 `EXPLAIN ANALYZE`。

仅重测分页、复用已有通知证据时：

```powershell
uv run python benchmarks/run_resume_evidence.py --skip-browser --rounds 6 --concurrency 1
```

简历中的 A/B 必须来自同一次完整对比。若延迟关联在该负载下并未更快，应如实报告，不用历史数据或不同查询范围拼接“提升”。本地短时单实例吞吐不是生产 SLA 或系统最大容量。

## 统计信息、覆盖索引和页深分层测试

```powershell
uv run python benchmarks/run_resume_evidence.py --skip-browser --pagination-study --rounds 4 --concurrency 1 --http-requests 250 --sql-requests 500
```

预约数固定 10,000，单并发，页大小 20，分别固定第 1、250、500 页（OFFSET 为 0、4,980、9,980）。在同一新建隔离库中比较当前生产索引和实验索引 `idx_resume_user_college_id(user_id, college_id, id)`；候选索引仅在临时库创建/删除，不进入生产模型或迁移。每轮交替索引状态和分页方案执行顺序，轮间轮换页深执行顺序，避免总由某个方案先运行。

每次切换索引阶段均执行 `ANALYZE TABLE reservation` 并检查成功。保存刷新前后索引基数、两种主查询的 JSON/实际执行计划，以及 ID 子查询执行计划。无 `FORCE INDEX`；覆盖验证要求优化器实际选择候选索引，且 JSON 计划显示 `using_index=true`，同时检查完整延迟关联语句内的 ID 分页路径。

每个索引状态、页深、分页方案累计 2,000 条 SQL 样本和 1,000 条 HTTP 样本，四轮各为 500/250 次，每个计时块先顺序预热 50 次。总计正式 SQL 24,000 次、HTTP 12,000 次。SQL 计时涵盖分页主 SELECT 的客户端执行、驱动往返及缓冲结果解码，排除连接池取连接、认证、COUNT、ORM 关联加载和响应序列化；它不是仅由 MySQL 内部统计的执行时间。HTTP 计时覆盖完整鉴权接口响应，排除登录、预热、JSON 校验和摘要计算。两层指标不能直接相减推算其他阶段耗时。

原始样本保存于 `pagination-study-samples.jsonl`；实时轮次结果为 `pagination-study-rounds.jsonl`；执行计划和统计信息为 `pagination-study-plans.json`；最终分层汇总为 `pagination-study.json`。比较各阶段 SQL 与 HTTP 返回摘要，正式请求记录起止单调时钟并核验区间无重叠。默认汇总为每个独立分层的全部样本最近秩分位数，不把不同页面混算或平均各轮 P95。夹具为单学院单用户的已完成预约，覆盖固定页深下的个人预约读取，不声称代表所有租户/用户分布。

常规全页基准也已在造数后增加 `ANALYZE TABLE`，旧报告中的未主动刷新统计信息数据保留用于追溯，应与新协议区分。

## 10 万条预约测试数据与复测

```powershell
uv run python benchmarks/run_resume_evidence.py --skip-browser --pagination-study --rows 100000 --rounds 4 --concurrency 1 --http-requests 125 --sql-requests 250
```

`--rows 100000` 在本次新建隔离库内生成 100,000 条已完成预约，仍为 100 台设备、单学院单用户，按 1,000 条批次插入并一次提交。生成器会拒绝在非 `lab_resume_*` 库中创建 10 万条夹具。原有 1 万条默认值与旧读取容量工具的固定页数协议不变；非默认数据量仅通过 `--pagination-study` 使用。

10 万条数据共 5,000 页，每页 20 条，固定第 1、2,500、5,000 页（OFFSET 为 0、49,980、99,980），均符合生产跳过记录上限。四轮同索引 A/B、统计刷新、计划验证、顺序预热和数据摘要校验方法沿用上节。每个索引/页深/方案分层累计 SQL 1,000 条样本、HTTP 500 条样本，总计 SQL 12,000 次、HTTP 6,000 次；样本数与 1 万条实验不同，不能把两个实验的数字拼成优化前后指标。

所有数据和实验索引都在本次隔离库中创建，脚本退出后自动删除该库。上述命令可重新生成 10 万条夹具并完成整套验证，不向已有业务库写入测试预约。实验索引仍仅为验证，不等于已部署的生产迁移。
