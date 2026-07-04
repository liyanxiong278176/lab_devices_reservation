# 实验设备预约平台 —— JMeter 压测

Phase 4 论文实测。三场景脚本 + 一键运行 + 真实数据，用于验证「防超约」与读取接口性能。

## 环境

| 项 | 值 |
|---|---|
| 压测工具 | Apache JMeter 5.6.3（`justb4/jmeter:latest` Docker 镜像，宿主机不装） |
| 被压服务 | 后端 Spring Boot，宿主机 `localhost:8080`，context-path `/api` |
| 容器→宿主机 | `host.docker.internal:8080`（Docker Desktop 自动解析） |
| 中间件 | `lab-mysql` / `lab-redis` / `lab-rabbitmq` 容器（docker compose） |
| 数据库 | seed: 用户 `admin/admin123`（SYS_ADMIN）、`bench_stu_1783167395/pass1234`（STUDENT，压测前用 `/api/auth/register` 建的专用账号）、设备 id=1（IDLE, need_approval=1, max_reservation_hours=4） |
| 鉴权 | JWT Bearer。每个线程在 `Once Only Controller` 内先 `POST /api/auth/login`，`JSON Extractor` 抽 `$.data.accessToken` 到线程变量 `TOKEN`，主请求带 `Authorization: Bearer ${TOKEN}` |
| 业务返回约定 | HTTP 恒为 200，业务码在响应体 `"code":200 / 409 / ...`（`Result` 包装 + `GlobalExceptionHandler` 无 `@ResponseStatus`）。故断言全部走 **响应体包含 `"code":200`**，而不是 HTTP 状态码 |

## 文件

```
benchmark/
├── jmeter/
│   ├── lock-concurrency.jmx   # 50线程同设备同时段并发预约，验防超约
│   ├── recommend-qps.jmx      # STUDENT GET /api/recommendations?limit=10
│   └── dashboard-qps.jmx      # SYS_ADMIN GET /api/dashboard/overview
├── run.sh                     # ./benchmark/run.sh <lock|recommend|dashboard>
├── out/                       # 运行产物 *.jtl（已 .gitignore）
└── README.md
```

## 复现

前置：后端跑在宿主机 8080，middleware 起齐，`bench_stu_1783167395/pass1234` 已注册（不存在则先跑一次：`curl -X POST http://localhost:8080/api/auth/register -H 'Content-Type: application/json' -d '{"username":"bench_stu_1783167395","password":"pass1234","realName":"BenchStu","userType":"STUDENT"}'`）。

```bash
docker pull justb4/jmeter:latest          # 仅首次
./benchmark/run.sh lock                   # 防超约并发
./benchmark/run.sh recommend              # 推荐接口 QPS
./benchmark/run.sh dashboard              # 仪表盘接口 QPS
```

每次输出写到 `benchmark/out/<scenario>.jtl`（CSV，含 elapsed/success/failureMessage 等列）。
环境变量可覆盖：`HOST`、`PORT`、`DEVICE_ID`、`LOCK_START`、`LOCK_END`、`LOGIN_USER`、`LOGIN_PASS`。
> Windows / Git Bash 注：`run.sh` 内 docker 调用设了 `MSYS_NO_PATHCONV=1`，避免 `/benchmark` 容器内路径被 MSYS 改写。直接 `bash benchmark/run.sh <scn>` 即可。

锁场景默认拿「明天 14:00–15:00」作为冲突时段。**重跑会复用同一时段**，此时该 slot 已被上一轮赢家占用 → 50 个请求全 409。重跑前请覆盖：`LOCK_START=2026-08-01T14:00:00 LOCK_END=2026-08-01T15:00:00 ./benchmark/run.sh lock`。

## 场景设计

| 场景 | 线程 | 循环 | 同步 | 断言 | 目的 |
|---|---|---|---|---|---|
| `lock` | 50 | 1 | **Synchronizing Timer**（groupSize=50, timeout=10s）把 50 个请求打到同一瞬 | 响应体含 `"code":200` 记 1 成功；BeanShell Assertion 把 `"code":409` 计入 `lock_conflict`、其余计入 `lock_other` | 证明 Redisson 锁 + DB 唯一索引双层防超约 |
| `recommend` | 100（20s ramp） | 20 | 无 | `"code":200` | 测推荐接口吞吐 + 时延分布（Redis 缓存命中） |
| `dashboard` | 100（20s ramp） | 20 | 无 | `"code":200` | 测富聚合接口吞吐 + 时延（Redis 缓存命中，重查询） |

锁场景 body：
```json
{"deviceId":1,"startTime":"2026-07-05T14:00:00","endTime":"2026-07-05T15:00:00","purpose":"jmeter-lock-bench"}
```
- 时段对齐 15 分钟槽、落在 08:00–22:00 工作窗内（`SlotCalculatorService` 校验）。
- 4 个 15 分钟槽，远小于设备 `max_reservation_hours=4`（=16 槽上限）。

## 实测数据（2026-07-04）

宿主机：Windows 11，JMeter 跑在 `justb4/jmeter` 容器内，后端跑在宿主机 JDK（非容器）。

### 1. Lock 并发 —— 防超约验证 ✅

50 线程、Synchronizing Timer 同步、同一设备 id=1 + 同一时段 2026-07-05 14:00–15:00：

| 指标 | 值 |
|---|---|
| 预约请求总数 | 50 |
| **业务成功（`"code":200`）** | **1** |
| **业务冲突（`"code":409` 该时段已被占用）** | **49** |
| 其它 | 0 |
| HTTP 状态 | 50 个全部 200（业务码在 body） |
| 预约请求时延（ms） | min=436  P50=935  P95=1246  P99=1273  max=1290 |

**结论：恰好 1 个成功、49 个冲突，证明防超约生效。** 时延偏高是 Synchronizing Timer 把 50 个请求压到同一瞬、全部进入 `ReservationLock.acquire` 的分布式锁串行队列所致（预期行为，锁本身是防超约的核心）。

### 2. Recommend QPS —— `GET /api/recommendations?limit=10`（STUDENT）

100 线程、20s ramp、每线程 20 次：

| 指标 | 值 |
|---|---|
| 样本数 | 2000 |
| 错误率 | 0.00% |
| **吞吐** | **104.0 req/s** |
| 时延（ms） | avg=12.2  **P50=10**  P90=17  **P95=22**  **P99=42**  min=6  max=357 |

### 3. Dashboard QPS —— `GET /api/dashboard/overview?groupBy=device&days=30`（SYS_ADMIN）

100 线程、20s ramp、每线程 20 次：

| 指标 | 值 |
|---|---|
| 样本数 | 2000 |
| 错误率 | 0.00% |
| **吞吐** | **102.9 req/s** |
| 时延（ms） | avg=23.1  **P50=21**  P90=30  **P95=35**  **P99=59**  min=13  max=101 |

### 汇总

| 场景 | 线程 | 样本 | 吞吐(req/s) | avg(ms) | P50 | P95 | P99 | 错误率 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| Lock 并发 | 50 同步 | 50 | — (瞬时) | 812 | 935 | 1246 | 1273 | 49 conflict(预期) | 1 成功 / 49 冲突，防超约✅ |
| Recommend | 100 | 2000 | 104.0 | 12.2 | 10 | 22 | 42 | 0% | Redis 缓存命中 |
| Dashboard | 100 | 2000 | 102.9 | 23.1 | 21 | 35 | 59 | 0% | 重聚合查询 + Redis 缓存 |

### Redis 缓存效果（冷启动 vs 缓存命中）

把每个 QPS 场景的前 1/3 请求视为「冷（缓存未命中/部分未命中）」、后 2/3 视为「暖（命中）」：

| 场景 | 阶段 | n | avg(ms) | P50 | P95 |
|---|---|---|---|---|---|
| Recommend | 冷 | 666 | 13.2 | 12 | 25 |
| Recommend | 暖 | 1334 | 11.6 | 9 | 22 |
| Dashboard | 冷 | 666 | 24.2 | 22 | 40 |
| Dashboard | 暖 | 1334 | 22.5 | 21 | 33 |

暖段相对冷段：Recommend avg −12% / P50 −25%；Dashboard avg −7% / P95 −18%。缓存命中对 P50/P95 改善明显，但因 DB 内 seed 数据量小、聚合本身不算重，整体差距有限 —— 论文里据此说明「缓存收益随数据量/聚合复杂度上升而放大」。

## 结论

1. **防超约成立**：50 并发抢同一设备同一时段 → 恰好 1 个成功、49 个 `RESERVATION_CONFLICT(409)`。双层防线：`ReservationLock.acquire`（Redisson 分布式锁，按 `(deviceId, date)` 串行）+ `reservation_item` 表 `UNIQUE(device_id, date, slot_index)` 唯一索引兜底（并发漏过锁时抛 `DuplicateKeyException` → `BusinessException(RESERVATION_CONFLICT)`）。代码见 `ReservationServiceImpl#create`。
2. **读接口性能充足**：Recommend 与 Dashboard 在 100 并发下吞吐 ~103 req/s、P95 ≤ 35ms、P99 ≤ 59ms、零错误，满足校园实验室预约平台的交互时延要求。
3. **缓存收益可测**：Redis 缓存命中使 Recommend P50 从 12ms 降到 9ms、Dashboard P95 从 40ms 降到 33ms；在当前小数据量下差距温和，随数据规模扩大收益会更显著。

## 故障排查

- **lock 重跑全 409**：该 slot 已被上一轮赢家占用。用 `LOCK_START/LOCK_END` 环境变量换一个未来时段再跑。
- **recommend 报 401**：`bench_stu_1783167395` 不存在或密码错。重新注册（见上文 curl）或用 `LOGIN_USER/LOGIN_PASS` 覆盖。
- **dashboard 报 403**：登录账号不是 LAB_ADMIN/SYS_ADMIN；默认 `admin/admin123` 满足，自定义账号注意角色。
- **容器连不上后端**：确认后端在宿主机 8080 监听，且 Docker Desktop 的 `host.docker.internal` 解析正常（Windows/macOS 自带；Linux 需 `--add-host=host.docker.internal:host-gateway`）。
