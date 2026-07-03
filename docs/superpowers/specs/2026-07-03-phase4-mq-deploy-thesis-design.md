# 阶段4 设计：RabbitMQ 接入 + Docker 一键部署 + 论文素材（drawio + JMeter）

- 日期：2026-07-03
- 承接：阶段1-3 已合并 main（HEAD `fb2bc3c`，含今日 App.vue/vite.config 修复）
- 范围：RabbitMQ 真接入（双亮点）+ Docker 全容器化一键部署 + 论文素材（drawio 图集）+ JMeter 压测
- 关联文档：阶段2+3 spec `2026-07-02-phase2-3-highlights-and-frontend-design.md`

---

## 1. 背景与定位

阶段2+3 已交付四亮点（Redisson 锁 / STOMP 推送 / ECharts 驾驶舱 / 混合推荐）与 Vue3 前端，`docker-compose.yml` 已预装 mysql/redis/rabbitmq 三中间件，但 **RabbitMQ 仅预装、代码未接入**。阶段4 完成最后一块：让 RabbitMQ 真正承担业务职责、把整套系统容器化一键起、并产出可直接用于毕设论文与答辩的素材与实测压测数据。

## 2. 目标 / 非目标

**目标**
- RabbitMQ 接入两个真实业务点：① 现有 9 处同步通知改异步（解耦/削峰/最终一致）；② 预约审批通过后「超时未签到自动取消」（TTL+死信延迟队列）。
- Docker 全容器化：后端 jar 镜像 + 前端 nginx 镜像 + 中间件，`docker compose -f docker-compose.prod.yml up -d --build` 一键起全套，浏览器单端口访问。
- 论文素材：6 类 drawio 图（源文件 + PNG）+ JMeter 实测压测数据与可复现脚本。

**非目标**
- 不做高可用集群/多节点 RabbitMQ（单节点够毕设）。
- 不引入 K8s（docker compose 足够）。
- 不重构阶段1-3 已验证的业务逻辑（仅在通知调用点做「同步→异步」切换）。
- 不写完整毕业论文正文（只产出图、压测数据、架构说明素材）。

## 3. 总体策略（纵切 S1→S2→S3，子代理逐任务）

依赖链清晰：**代码定型(S1 MQ) → 容器化(S2) → 压测/文档(S3)**——压测与截图针对的是最终部署态系统。与阶段2+3 同模式：每切片独立验证、子代理实现、关键切片过 code review。

---

## 4. S1 — RabbitMQ 接入（双亮点）

### 4.1 依赖与配置
- `pom.xml` 加 `spring-boot-starter-amqp`。
- `application-dev.yml` / `application-prod.yml` 加 `spring.rabbitmq.{host,port,username,password,virtual-host}`（dev 连 localhost、prod 连容器名 `rabbitmq`）。
- 新增 `config/RabbitMQConfig.java`：`@EnableRabbit` + 声明所有交换机/队列/绑定（`Declarables` 或 `@Bean`）。

### 4.2 亮点① 异步通知解耦
把现有 9 处同步 `notificationService.notify(...)`（`ApprovalServiceImpl` ×2、`RepairReportServiceImpl` ×3、`ReservationServiceImpl` ×4）改为发 MQ 消息，消费者异步复用 `NotificationService.notify` 写 DB+WS。

**拓扑**
| 元素 | 名 | 类型/参数 |
|---|---|---|
| 交换机 | `notify.exchange` | direct, durable |
| 队列 | `notify.queue` | durable, `x-dead-letter-exchange=notify.dlx`（失败兜底） |
| 绑定 | — | routingKey `notify` |
| 死信交换机 | `notify.dlx` | direct, durable |
| 死信队列 | `notify.dlq` | durable（消费失败 N 次后落此，记日志/告警） |
| DLX 绑定 | — | `notify.dlx` → `notify.dlq`，routingKey `notify`（与原 RK 一致） |

**消息体**（JSON，`NotificationMessage`）
```json
{ "msgId": "<uuid>", "userId": 25, "type": "APPROVAL",
  "title": "预约已通过", "content": "...", "relatedId": 12, "relatedType": "RESERVATION" }
```

**组件**
- `NotificationProducer`：`notify(userId,type,title,content,relatedId,relatedType)` → 构造 `NotificationMessage`（msgId=UUID）→ `rabbitTemplate.convertAndSend("notify.exchange","notify",msg)`。**事务后投递**：内部用 `TransactionSynchronizationManager`，当前有事务则 `afterCommit` 发、无则直发（避免「事务回滚但消息已发」）。
- `NotificationConsumer`：`@RabbitListener(queues="notify.queue")` → **幂等校验**（Redis `SET NX msgId TTL 24h`，命中则跳过）→ 调 `NotificationService.notify(...)`（原逻辑零改动，只是换到消费者线程执行）。
- 调用方（9 处）：`notificationService.notify(...)` → `notificationProducer.notify(...)`，签名一致、改动机械。

### 4.3 亮点② 延迟队列「超时未签到自动取消」
审批通过时发延迟消息，TTL 到期由死信路由到取消队列，消费者检查状态：若仍 `APPROVED` 且未签到 → 置 `CANCELLED` + 通知用户「超时未签到已自动取消」。

**拓扑（纯原生 TTL+DLX，不装插件）**
| 元素 | 名 | 类型/参数 |
|---|---|---|
| 延迟队列 | `reservation.timeout.queue` | durable, `x-dead-letter-exchange=reservation.cancel.exchange`, `x-dead-letter-routing-key=reservation.cancel`（**无消费者**，仅靠 TTL 过期死信） |
| 取消交换机 | `reservation.cancel.exchange` | direct, durable |
| 取消队列 | `reservation.cancel.queue` | durable |
| 绑定 | — | routingKey `reservation.cancel` |

- 发消息时设 `MessageProperties.expiration`（ms）= `预约开始时间 - now + 宽限期`（demo 用配置项 `lab.reservation.signin-grace-minutes` 调到 1-2 分钟便于演示）。
- `ReservationTimeoutConsumer`：`@RabbitListener(queues="reservation.cancel.queue")` → 按 reservationId 查库 → 状态仍 `APPROVED`（签到会流转到 `IN_USE`，故未签到 = 仍 APPROVED）→ 调 `ReservationService` 取消 + `NotificationProducer.notify` 通知。

### 4.4 可靠性工程点（答辩得分项，逐条实现+测试）
1. **事务后投递**：`afterCommit`（4.2）。
2. **幂等消费**：Redis `SET NX msgId`（4.2/4.3 共用）。
3. **队头阻塞取舍**：消息级 TTL 存在队头阻塞（队首消息未过期则其后消息即便过期也不出队）。预约场景消息按审批时间近似有序、TTL 相近，影响可控；设计文档与论文**诚实写明此限制**，作为已知工程取舍（答辩如被问及，回答「可用 delayed-message-exchange 插件消除，但增加部署依赖，权衡后选原生方案」）。
4. **失败兜底**：消费异常 → 重试（Spring Retry，3 次指数退避）→ 仍失败进 `notify.dlq` 记日志。
5. **可靠投递**（可选增强）：开启 publisher confirm。

### 4.5 状态机 / Schema 变更
- 预约状态流转新增 `APPROVED --(timeout)--> CANCELLED`。
- `Reservation` 若现无「取消原因」字段，则加 `cancel_reason`（枚举 `USER`/`TIMEOUT`），走 **V4 Flyway 迁移**（V1-V3 不可改，见项目约束）。plan 阶段先核实 `Reservation` 实体现状再定是否需要 V4。

### 4.6 测试策略（TDD）
- `NotificationProducerTest`：verify `rabbitTemplate.convertAndSend` 被调、消息含 msgId。
- `NotificationConsumerTest`：收到消息 → 调 `NotificationService.notify`；重复 msgId → 跳过（幂等）。
- `ReservationTimeoutConsumerTest`：mock 预约状态，`APPROVED`→取消+通知、`IN_USE`→不动（已签到不取消）。
- **延迟队列集成测试**：连本地 compose 的 rabbitmq 容器（与阶段2+3 锁 IT 同策略：本地中间件，非 Testcontainers），发短 TTL（2s）消息到 `reservation.timeout.queue` → 轮询断言 `reservation.cancel.queue` 收到死信。用越界/隔离数据避免污染。

---

## 5. S2 — Docker 全容器化一键部署

### 5.1 后端 Dockerfile（multi-stage）
```
# stage1 builder: maven:3.9-eclipse-temurin-17  (先 copy pom 跑 dependency cache 层, 再 copy src, mvn -B package -DskipTests)
# stage2 runtime: eclipse-temurin:17-jre-jammy  (copy target/*.jar /app.jar)
# ENTRYPOINT ["java","-jar","/app.jar","--spring.profiles.active=prod"]
```

### 5.2 前端 Dockerfile + nginx（multi-stage）
```
# stage1 builder: node:20-alpine + corepack(pnpm), pnpm install --frozen-lockfile, pnpm build
# stage2: nginx:alpine, copy dist → /usr/share/nginx/html, copy nginx.conf
```
**`frontend/nginx.conf`**：
- `location /` → 静态 `try_files $uri $uri/ /index.html`（SPA history 路由回退）
- `location /api/` → `proxy_pass http://app:8080`
- `location /ws` → `proxy_pass http://app:8080` + `Upgrade`/`Connection: upgrade` 头（WebSocket）

### 5.3 前端 baseURL / env 修复（顺带修部署隐患）
核查实际硬编码点：`useWebSocket.ts`（WS URL `http://localhost:8080/api/ws`）与 `vite.config.ts`（proxy target `localhost:8080`）；`request.ts` 已用相对 `baseURL: '/api'`，**无需改**。改动：
- WS URL：`useWebSocket.ts` 改为基于 `window.location` 的同源 `/ws`（prod 经 nginx 反代到后端），dev 经 `VITE_WS_BASE` 指向 `http://localhost:8080`。
- proxy target：`vite.config.ts` 的 `/api`、`/ws` proxy target 保留 dev 默认 `localhost:8080`（仅 dev 生效；prod 走 nginx、不经 vite）。
- 新建 `.env.development`（dev 指向 `localhost:8080`）与 `.env.production`（prod 相对路径）——当前项目无任何 `.env.*`、亦无 `import.meta.env` 使用。

### 5.4 application-prod.yml
- `spring.datasource.url`: `jdbc:mysql://mysql:3306/lab_reservation...`，密码 `${DB_PASSWORD}`。
- `spring.data.redis.host`: `redis`。
- `spring.rabbitmq.host`: `rabbitmq`，user/pass `${RABBITMQ_USERNAME}`/`${RABBITMQ_PASSWORD}`。
- `jwt.secret`: `${JWT_SECRET}`。
- Flyway `baseline-on-migrate: true`（prod 容器首次起若库为空则跑迁移）。

### 5.5 docker-compose.prod.yml
- 复用 mysql/redis/rabbitmq 三服务（独立完整声明，prod 自洽）。**注意**：dev `docker-compose.yml` 给 mysql/redis 配了 healthcheck 但 **rabbitmq 没有**；prod compose 必须给 rabbitmq 加 healthcheck（如 `rabbitmq-diagnostics -q ping`），否则 `app` 的 `depends_on: condition: service_healthy` 会一直等不到 rabbitmq 转 healthy。
- 新增 `app`：`build: ./`，`depends_on`（mysql/redis/rabbitmq `condition: service_healthy`），`environment` 注入 `${DB_PASSWORD}` 等，内部端口 8080（不强制对外暴露）。
- 新增 `frontend`：`build: ./frontend`，`ports: ["80:80"]`，`depends_on: [app]`。
- 一键：`docker compose -f docker-compose.prod.yml up -d --build`。

### 5.6 一键启动与验证
浏览器访问 `http://localhost`（nginx 80）→ 登录 → 驾驶舱 → 触发 WS 推送，全链路经 nginx 反代走通；`docker compose -f ... ps` 三中间件 healthy + app + frontend Up。

---

## 6. S3 — 论文素材与压测

### 6.1 drawio 图集（`docs/thesis/drawings/`，源 `.drawio` + 导出 `.png`）
1. **系统总体架构图**（分层：前端/网关 nginx/业务服务/中间件 MySQL·Redis·RabbitMQ/数据，标注技术栈）。
2. **容器部署拓扑图**（docker-compose.prod 服务依赖、网络、端口、数据卷）。
3. **ER 图**（核心表：user/device/category/reservation/reservation_item/notification/repair_report/operation_log）。
4. **四亮点原理图**：
   - Redisson 分布式锁时序（并发预约→tryLock→看门狗→DB 唯一索引双层防线）。
   - STOMP/SockJS 推送时序（握手 token→SimpUserRegistry→convertAndSendToUser）。
   - 混合推荐打分流程（特征→α/β/γ/δ/ε 加权→理由→冷启动降级）。
   - ECharts 驾驶舱数据流（聚合→Redis 缓存→vue-echarts 三视角）。
5. **RabbitMQ 流程图**：异步通知链（producer→exchange→queue→consumer→DB+WS）+ TTL/DLX 延迟取消路径（timeout.queue→过期→cancel.exchange→cancel.queue→consumer）。
6. **预约全生命周期时序图**（创建→审批→【超时取消分支】→签到→归还，含 MQ/锁/推送交互）。

**drawio 产出方式**：原生 mxGraph XML（子代理按「节点+连线+布局坐标」规格生成），drawio desktop CLI（`draw.io.exe --export --format png`）导出 PNG。Markdown 文档引用 PNG。

### 6.2 JMeter 压测（`benchmark/jmeter/*.jmx` + `benchmark/README.md`）
- **锁并发**：线程组并发打「同设备同时段建预约」，断言恰好 1 成功、其余 `RESERVATION_CONFLICT`（实证 Redisson 锁+DB 索引双层防超约）。
- **接口 QPS**：打 `/recommendations`、`/dashboard/overview`，出吞吐量与 P50/P95/P99 延迟（对比 Redis 缓存命中 vs miss）。
- **WS 并发**：脚本开 N 个 STOMP/SockJS 连接，测推送到达延迟与连接数上限。
- `benchmark/README.md`：实测数据表 + 结论文字 + 关键图表。脚本 `.jmx` 归档可复现。
- **JMeter 可用性**：plan 阶段确认本机 `jmeter` CLI；若缺失，引导用户安装（JMeter 需 JDK，本机已有 JDK17）。

### 6.3 交付结构
```
docs/thesis/
  architecture.md        # 总体架构说明（配图1/2）
  data-model.md          # ER 说明（配图3）
  highlights.md          # 四亮点 + RabbitMQ 原理（配图4/5）
  flow.md                # 业务时序说明（配图6）
  drawings/*.drawio + *.png
  screenshots/           # 三角色界面截图（答辩用）
benchmark/
  jmeter/*.jmx
  README.md              # 压测方案 + 实测数据 + 结论
```

---

## 7. 切片交付计划（纵切）
- **S1 RabbitMQ**：依赖→config→异步通知（producer/consumer/幂等/事务后投递）→延迟队列→状态机/V4→TDD+IT。子代理逐任务，过 code review。
- **S2 Docker**：后端 Dockerfile→前端 Dockerfile+nginx→baseURL 修复→application-prod.yml→docker-compose.prod.yml→一键起验证。
- **S3 论文+压测**：drawio 图集（子代理逐图）→JMeter 压测脚本+实测→README/截图。

## 8. 风险与取舍
| 风险 | 缓解 |
|---|---|
| drawio CLI 无头导出受限（Electron 依赖显示） | 兜底：手动用 draw.io 打开导出 PNG；优先验证 CLI |
| 消息级 TTL 队头阻塞 | 文档诚实说明；场景近似有序、影响可控；备选插件方案留论文讨论 |
| RabbitMQ at-least-once 重复投递 | Redis `SET NX msgId` 幂等 |
| prod Flyway 首次迁移行为 | `baseline-on-migrate:true` + 验证；dev/prod 迁移一致 |
| JMeter 本机缺失 | plan 阶段确认，引导安装 |
| 容器内后端连中间件 host | 用 compose 服务名（mysql/redis/rabbitmq）作 host |

## 9. 验收标准（DoD）
- **MQ**：9 处通知改异步（生产者/消费者可追溯）、延迟队列超时取消可现场演示（短 TTL）、幂等+事务后投递有测试、延迟队列 IT 绿。
- **Docker**：`docker compose -f docker-compose.prod.yml up -d --build` 起全套，浏览器 `http://localhost` 走通 登录→驾驶舱渲染→WS 推送。
- **论文/压测**：6 张 drawio 图（.drawio + .png）、JMeter 实测数据 + .jmx 归档、`benchmark/README.md`、三角色截图。
- **全回归**：后端测试全绿（阶段1-3 零回归 + MQ 新增）、前端 `pnpm build` + vitest 绿。

## 10. 与既有实现关系
- `NotificationService.notify` 逻辑保留（消费者内部复用），仅调用入口由「业务同步」改为「MQ 异步」。
- `docker-compose.yml`（dev 中间件）保留不动，新增 `docker-compose.prod.yml`。
- Flyway 迁移 V1-V3 不动；如需 cancel_reason 走 V4。
- 前端 baseURL 修复同时解决阶段2+3 遗留的 Minor（localhost 硬编码）。
