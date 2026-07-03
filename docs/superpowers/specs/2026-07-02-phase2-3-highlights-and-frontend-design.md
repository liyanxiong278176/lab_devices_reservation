# 阶段2+3 设计规格：后端四大亮点 + Vue3 三端前端（高校实验室设备智能预约与管控平台）

- **状态**：已通过用户分节评审，待规格评审（spec review）
- **日期**：2026-07-02
- **范围**：原四阶段路线中的**阶段2（后端亮点）与阶段3（前端）合并为一个连续工程**，按纵切功能片交付
- **协作模式**：用户为 Java/Spring 熟手，要求高效产出、可 review、可答辩；前端须美观、无"AI 味"
- **上游**：阶段1 已完成并合并 main（18 提交、39 测试全绿），规格见 `2026-07-01-phase1-backend-mvp-design.md`

---

## 1. 背景与定位

阶段1 已交付可独立运行的后端核心（鉴权/RBAC/设备/预约含 DB 层防超约/审批/签到归还/报修/DB 通知/Dashboard 数字）。本规格把原路线的阶段2（Redis 锁、智能推荐、WebSocket 推送、ECharts 驾驶舱）与阶段3（Vue3 三端前端）**合并**，因为 ECharts 可视化与 WebSocket 推送的真正价值需前端才能端到端演示。

**交付策略：纵切功能片**——先立前端骨架 + 核心页（让 app 可用），再逐个亮点切成「后端 API + 前端页」依次交付，每片做完即可演示。

**阶段2+3 的目标**：交付一个前后端贯通、四大亮点可在真实 UI 中演示、有后端单测/集成测试与前端关键单测的完整系统。答辩技术核心（尤其 Redis 分布式锁双层防线、可解释推荐）在本阶段夯实并可视化。

---

## 2. 范围

### 2.1 纳入范围（In Scope）

- **中间件 compose**：`docker-compose.yml`（mysql + redis + rabbitmq），`docker compose up` 一键起
- **后端四大亮点**：
  - **S2 锁片**：Redisson 分布式锁接入预约创建，与 DB 唯一索引形成「双层防线」
  - **S3 推送片**：STOMP/SockJS WebSocket，通知由轮询升级为实时推送
  - **S4 驾驶舱片**：富指标聚合 API（利用率/热力/分布），按角色 scope
  - **S5 推荐片**：混合启发式推荐 API（可解释 + 冷启动降级 + Redis 缓存）
- **前端工程**：Vite + Vue3 + TS + Element Plus（Cal.com 视觉基准）+ Pinia + Vue Router + axios + ECharts + STOMP 客户端
- **S1 核心页对接**：Phase1 全部 API 前端化，三角色全流程可用
- **前端设计规范**：采用 [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) 的 **Cal.com DESIGN.md** 作为视觉契约，消除 AI 味
- **测试**：后端单测（推荐/锁/WS/驾驶舱）+ Redis 锁并发集成测试（Testcontainers-redis）；前端关键纯逻辑单测（Vitest）；Phase1 的 39 测试零回归

### 2.2 排除范围（Out of Scope，明确延后）

- **RabbitMQ 代码接入** —— compose 预装容器，但阶段2+3 代码**不接入** MQ（通知仍为 Phase1 直写 DB + Phase2 WS 直播）。MQ 真正接入（异步通知/重试/发件箱）留阶段4。
- **生产部署 / nginx / 静态资源打包进后端** —— 仅要求 `pnpm build` 成功产出可部署产物，实际部署留阶段4。
- **移动端原生 / 小程序** —— 仅响应式 Web。
- **定时巡检（爽约自动判定等）** —— 仍留扩展点。
- **第三方短信/邮件** —— 阶段4。

> YAGNI 边界：RabbitMQ 容器先备不用；前端不做全组件单测覆盖，只测关键纯逻辑。

---

## 3. 总体架构与切片交付

```
┌──────────────────────────────────────────────────────────┐
│  frontend/   Vite+Vue3+TS+Element Plus(Cal.com皮)+Pinia+ECharts+STOMP │
│       ↕ axios (REST) + STOMP/SockJS (WS)                    │
└──────────────────────────────────────────────────────────┘
       ↕ HTTP / WS
┌──────────────────────────────────────────────────────────┐
│  Spring Boot 后端 (Phase1 + 4 亮点)                          │
│   新增: Redisson锁 / 推荐API / 驾驶舱富指标API / WebSocket推送  │
└──────────────────────────────────────────────────────────┘
       ↕
┌──────────────┬──────────────┬────────────────┐
│  MySQL 8     │  Redis 7     │  RabbitMQ(预装)  │   ← docker-compose 一键起
│ (Flyway重建)  │ (锁/缓存)     │  (Phase4才接入)  │
└──────────────┴──────────────┴────────────────┘
```

### 3.1 切片交付顺序（一份 spec + 一份分片 plan）

| 片 | 内容 | 可演示物 |
|---|---|---|
| **S0 基建** | `docker-compose.yml`(mysql+redis+rabbitmq)；后端 Redis/WS/Redisson 配置；**前端 Vue 工程脚手架** + Cal.com DESIGN.md 落位 + Element Plus 主题换皮 + 登录 + 布局 + 路由守卫 + axios(token+401刷新) | 两端能起、能登录 |
| **S1 核心页对接** | Phase1 全部 API 前端化：设备浏览/检索、详情+日历、建预约、我的预约、通知(轮询)、审批、报修、用户管理、Dashboard 占位 | app 全流程可用（阶段3 主体） |
| **S2 锁片** | Redisson 锁接入 `ReservationServiceImpl.create`；并发 IT | 跨进程防超约实证（头牌） |
| **S3 推送片** | STOMP WebSocket 推送基础设施；通知由轮询升级为实时推送；前端通知中心/Toast | 两浏览器看实时推送 |
| **S4 驾驶舱片** | 后端富指标 API（利用率/热力/分布）；前端 ECharts 驾驶舱页 | 图表演示 |
| **S5 推荐片** | 后端推荐 API（混合启发式）；前端"为你推荐"区 | 个性化推荐演示 |

> S2 是纯后端片（对前端透明），放最前守住头牌；S3 紧跟因为要把 S1 建好的"轮询通知"升级成 WS；S4/S5 是加法。

---

## 4. 技术栈

### 4.1 后端新增依赖（追加 pom.xml，除注明外由 SB 父 POM 3.2.5 管版本）

| groupId:artifactId | 版本 | 用途 |
|---|---|---|
| org.springframework.boot:spring-boot-starter-data-redis | （父管理） | Lettuce 客户端（已在 pom） |
| org.springframework.boot:spring-boot-starter-websocket | （父管理） | STOMP + SockJS |
| org.redisson:redisson-spring-boot-starter | 3.31.0（property，S0 编译验证） | 分布式锁 RLock + 看门狗续期 |

### 4.2 前端栈（`frontend/` 独立 Vite 工程，pnpm）

| 库 | 版本 | 用途 |
|---|---|---|
| vite | ^5.2 | 构建/dev server，代理 `/api`+`/ws`→:8080 |
| vue | ^3.4 | `<script setup>` + Composition API |
| typescript | ^5.4 | 类型安全 |
| element-plus | ^2.7 | 组件库（主题映射到 Cal.com tokens） |
| @element-plus/icons-vue | ^2.3 | 图标 |
| pinia | ^2.1 + pinia-plugin-persistedstate | 状态 + 持久化(token) |
| vue-router | ^4.3 | history 模式 + 角色守卫 |
| axios | ^1.6 | HTTP + 拦截器 |
| echarts + vue-echarts | ^5.5 / ^7.0 | 驾驶舱图表（懒加载） |
| @stomp/stompjs + sockjs-client | ^7.0 / ^1.6 | WebSocket 实时推送 |
| dayjs | ^1.11 | 时间格式化（比 moment 轻） |
| vitest | ^1.6（dev） | 前端关键纯逻辑单测 |

---

## 5. 中间件 docker-compose

`docker-compose.yml`（仓库根）：

| 服务 | 镜像 | 端口 | 卷 | 说明 |
|---|---|---|---|---|
| mysql | mysql:8.0 | 3306:3306 | `mysql_data` | root/123456，库 `lab_reservation`；Flyway 自动重建 schema + 现有 V2 灌种子（V2 为阶段1已有迁移，非新工作） |
| redis | redis:7-alpine | 6379:6379 | `redis_data` | 无密码（dev）；锁 + 推荐/驾驶舱缓存 |
| rabbitmq | rabbitmq:3.13-management | 5672:5672, 15672:15672 | `rabbitmq_data` | guest/guest；**预装不用**，Phase4 接入 |

- `docker compose up -d` 一键起全部；`docker compose down -v` 清库重建。
- **dev profile 切到容器库**：`application-dev.yml` 的 datasource 改为容器 mysql（仍是 localhost:3306，端口映射一致）；现有本地 MySQL 数据不迁移（Flyway V2 重新灌种子，admin/admin123 与示例设备均在）。
- 现有 Flyway V1/V2/V3 已应用的历史与容器库无关——容器库是全新库，Flyway 从 V1 跑起，**V1-V3 不可改**的约束继续生效；schema 变更走 V4+ 新迁移。

---

## 6. S2 锁片 · Redis 分布式锁（防超约双层防线）

### 6.1 接入点与锁粒度

在 `ReservationServiceImpl.create` 中（slot 与时长校验之后、`reservationMapper.insert(r)` **之前**）加锁，`try/finally` 释放。锁粒度 = **(设备, 日期)**：预约跨几天就锁几个 `lock:dev:{deviceId}:{date}`，用 `RedissonMultiLock` 一次 `tryLock`。同设备同天的并发预约被串行化（冲突高发区），不同设备/不同天互不阻塞。

### 6.2 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 拿不到锁 | `tryLock(waitTime=3s, leaseTime=-1)`；3s 内拿不到才报 `RESERVATION_CONFLICT` | 避免"同设备同天但不重叠时段"被误判冲突；真正冲突由 DB 唯一索引兜底 |
| 锁过期 | `leaseTime=-1` → **Redisson 看门狗自动续期**（默认 30s 锁、每 10s 续） | 事务执行慢也不提前释放；**答辩亮点** |
| Redis 不可用 | **fail-open**：catch 异常 → 记 warn 日志 → 跳过锁 → 仅靠 DB 唯一索引 | DB 索引是 100% 正确性保证，Redis 仅挡并发 → 「Redis 挡 95%，DB 兜底 100%」双层防线故事 |
| 释放 | `finally` 内 `if (locked && multi.isHeldByCurrentThread()) multi.unlock()` | 幂等，防 IllegalMonitorState |

### 6.3 改造后骨架

```java
// ReservationServiceImpl.create，在 slot 计算、时长校验之后、insert 之前
Long deviceId = d.getId();   // d 为方法上方加载的 Device
Set<LocalDate> dates = slots.stream().map(SlotKey::date).collect(Collectors.toSet());
RLock[] locks = dates.stream()
    .map(date -> redissonClient.getLock("lock:dev:" + deviceId + ":" + date))
    .toArray(RLock[]::new);
RLock multi = redissonClient.getMultiLock(locks);

boolean locked = false;
boolean redisDown = false;
try {
    locked = multi.tryLock(3, -1, TimeUnit.SECONDS);   // leaseTime=-1 触发看门狗
} catch (Exception e) {           // Redis 连接异常
    redisDown = true;
    log.warn("Redis unavailable, fail-open to DB unique index", e);
}
if (!locked && !redisDown) {
    throw new BusinessException(ResultCode.RESERVATION_CONFLICT);  // 抢锁失败
}
try {
    reservationMapper.insert(r);                          // 仍可能被 DB 索引兜底
    for (SlotKey s : slots) { itemMapper.insert(...); }   // DuplicateKeyException 仍 catch → CONFLICT
} finally {
    if (locked && multi.isHeldByCurrentThread()) {
        try { multi.unlock(); } catch (Exception ignore) {}
    }
}
```

> 现有 `DuplicateKeyException → RESERVATION_CONFLICT` 路径**保留**（第二层防线），不删。

---

## 7. S3 推送片 · WebSocket 实时推送

### 7.1 协议与端点

- STOMP over SockJS（Spring 原生支持，SockJS 兜底无 WS 网络）。
- 连接端点 `/ws`（`.setAllowedOriginPatterns("*").withSockJS()`）；用户私有通道 `/user/queue/notifications`。
- `@EnableWebSocketMessageBroker` + `WebSocketConfig`：`/app` 前缀（client→server），`/user`、`/queue`（Spring 内置 user destination）。

### 7.2 鉴权（握手期 query token —— 实现修订）

> **实现修订（原计划为 STOMP CONNECT 头鉴权，已改）**：实测发现 `convertAndSendToUser(userId)` 依赖的 `SimpUserRegistry` 按**握手期 Principal** 键映射，而浏览器 WebSocket/SockJS **无法在握手 HTTP 请求上加自定义头**，故 CONNECT 帧里设的 Principal 不会注册到 registry（实测 `totalUsers=0` → 推送静默丢弃）。因此改为**握手期鉴权**：token 经 query 传入握手 URL（浏览器 WS 鉴权标准做法），`WsAuthHandshakeInterceptor` 校验 token、`JwtHandshakeHandler`（覆盖 `DefaultHandshakeHandler.determineUser`）把 userId 设为会话 Principal → 注册到 registry → `convertAndSendToUser` 可达。端到端已验证（学生建预约实时收到推送）。token 进 query 是浏览器 WS 的固有限制；如需避免可改 cookie/会话方案，本毕设接受此 trade-off。

```
前端                              后端
 │ 连 /api/ws?token=<jwt>            │
 │ ──────────────────────────────► │  WsAuthHandshakeInterceptor 校验token → attributes.wsUserId
 │                                   │  JwtHandshakeHandler.determineUser → 会话 Principal=userId
 │ STOMP CONNECT + SUBSCRIBE         │  注册到 SimpUserRegistry
 │ /user/queue/notifications ──────► │  之后 convertAndSendToUser(userId) 定向推
```

### 7.3 与现有通知的关系（双写，互不依赖）

`NotificationService.notify(...)` 改为：DB 持久化（Phase1 已有，保留——历史 + 未读角标）**+** WS 实时推送（Phase2 新增）。WS 推送失败（用户离线）无所谓，DB 行还在，下次进系统补上。

```java
notificationService.notify(userId, type, title, content, relatedId, relatedType) {
    Notification n = ...; notificationMapper.insert(n);                 // 持久化（不变）
    messagingTemplate.convertAndSendToUser(                             // 新增：实时推送
        String.valueOf(userId), "/queue/notifications",
        Map.of("id", n.getId(), "title", title, "content", content,
               "type", type, "createdAt", n.getCreatedAt()));
}
```

推送事件：预约状态全流转（成功/待审批/通过/拒绝/签到/归还/取消/违规/爽约）+ 报修状态（受理/解决/驳回）+ 待审批推送给 LAB_ADMIN。

### 7.4 前端（S3）

`@stomp/stompjs + sockjs-client`，登录后建连、登出断开、token 刷新自动重连；订阅 `/user/queue/notifications` → `ElNotification` 弹 toast + 头部未读角标 +1 + 可选刷新通知列表。`notificationStore` 管未读数与 WS 消息。

---

## 8. S4 驾驶舱片 · ECharts 数据驾驶舱

### 8.1 后端富指标（在 Phase1 `/dashboard/summary` 基础上加，scope 复用 `LabScopeHelper`）

| 图表 | ECharts 类型 | 口径 |
|---|---|---|
| 设备状态分布 | pie | IDLE/IN_USE/MAINTENANCE（沿用） |
| 预约趋势 | line | 近 30 天每日预约数（Phase1 的 7 天扩展到 30） |
| **设备利用率** | bar | 近 N 天 已占槽 / 可用槽（按设备或类目聚合）——「智能管控」核心指标 |
| **高峰时段热力** | heatmap | 周 × 时段 的预约密度矩阵 |
| 类目分布 | pie/bar | 各类目设备数 / 预约数 |
| 报修统计 | bar | PENDING/PROCESSING/RESOLVED/REJECTED |
| 审批/违规概览 | 数字卡 | 待审批(by scope)、本周违规/爽约 |

利用率/热力查询为重聚合 → **Redis 缓存 5 分钟**（key 按 scope+维度+天数）。

### 8.2 角色三视角（每角色一个聚合端点）

- **STUDENT** `GET /dashboard/me`：我的预约(按状态)、我的近 30 天趋势、我的常用类目、未读通知数。
- **LAB_ADMIN** `GET /dashboard/overview`：自辖实验室的 设备/利用率/今日预约/待审批/报修/趋势/热力。
- **SYS_ADMIN** `GET /dashboard/overview`：全局全部指标 + 跨实验室对比。

> 一次请求返回该角色全部 widget 数据（减少前端往返）；保留 Phase1 `/dashboard/summary` 兼容。

### 8.3 前端（S4）

`vue-echarts` 包装懒加载；Element Plus `el-row/el-col` 响应式栅格；路由 meta 角色守卫 → 渲染对应 widget 集；mount 时拉对应端点，手动刷新（实时性非必需）。

---

## 9. S5 推荐片 · 智能推荐（混合启发式）

### 9.1 打分公式（纯 SQL + Java，无 ML 库）

```
Score(设备d, 用户u) =
    α·类目亲和度(d.categoryId, u)      // 用户历史预约里该类目占比
  + β·实验室亲和度(d.labId, u)         // 该实验室占比
  + γ·全局热度(d)                      // 近 30 天全站预约次数(归一化 0~1)
  + δ·标签命中(d.tags, u.偏好标签)     // 设备 tags(JSON) ∩ 用户偏好标签
  − ε·已用惩罚                         // 用户已约/已用过 → 降权
权重 α/β/γ/δ/ε 配置在 yml，可调。
```

- **数据源**：全部来自现有表（reservation/device），**无需改 schema**。
- **冷启动**：新用户无历史 → α=β=0，退化为纯热度推荐（γ 主导）。
- **可解释（杀手特性）**：返回**推荐理由**——"因你常约【显微镜】类目" / "近 30 天热门设备"。演示比黑盒分有说服力。
- **过滤**：排除 MAINTENANCE 设备；用户当前有活跃预约的设备降权（不硬删）。
- **缓存**：结果按用户 Redis 缓存 5 分钟（key `rec:u:{userId}`）。

### 9.2 接口

`GET /recommendations?limit=10` → `[{deviceId, name, score, reason, ...设备摘要}]`（STUDENT；LAB_ADMIN/SYS_ADMIN 可选）。理由由得分主项反推（类目亲和最高→"常约类目"；热度最高→"热门设备"）；得分主项并列（差距 < ε）时优先返回亲和度理由，保持个性化口吻。

---

## 10. 前端工程架构

### 10.1 目录（`frontend/src/`）

```
api/          request.ts(axios实例+拦截器) + 模块拆(auth/device/reservation/approval/repair/notification/user/dashboard/recommendation)
router/       index.ts + guard.ts(token校验 + 角色meta校验)
stores/       user(token/角色/权限+login/refresh/getMe,持久化) · notification(未读数+WS) · app(布局)
layouts/      MainLayout.vue(顶栏未读角标 + 侧栏角色菜单 + router-view)
views/        login · dashboard · device · reservation · approval · repair · user · recommendation
components/   通用 + charts/(ECharts 包装)
composables/  useWebSocket · useEcharts · usePermission
directives/   v-permission(按 perm_code 隐藏按钮)
types/        TS 类型(对齐后端 VO)
utils/        format · dayjs
```

### 10.2 路由与守卫

history 模式；路由 `meta: { roles: [...], requireAuth: true }`。全局 `beforeEach`：无 token → `/login`；角色不匹配 → 403 页；token 临期主动 refresh。组件懒加载按需分包。菜单由 `meta.roles` ∩ 用户角色动态生成。

### 10.3 状态与权限

`userStore`（持久化）+ `notificationStore`（WS 消息 → 角标++/toast）+ `appStore`（布局）。`v-permission` 指令按 `perm_code` 控按钮（如"审批"钮需 `device:approve`）；`usePermission` 提供 `hasPerm/hasRole`。

### 10.4 角色·页面矩阵

| 页面 | STUDENT | LAB_ADMIN | SYS_ADMIN |
|---|---|---|---|
| 登录 / 驾驶舱(角色视角) / 设备浏览检索详情日历 / 建预约 / 我的预约 / 我的通知 / 提交报修·我的报修 | ✓ | ✓ | ✓ |
| 为你推荐 | ✓ | 可选 | — |
| 设备管理(CRUD) / 待审批(通过拒绝批量) / 签到归还 / 报修处理(take·resolve·reject) | — | 自辖 | 全局 |
| 用户管理 / 实验室·分类管理 / 操作日志 | — | — | ✓ |

### 10.5 API 层

`request.ts`：baseURL `/api`；请求拦截注入 `Authorization: Bearer ${token}`；响应拦截解包 `Result`（code===200 返 data；否则 `ElMessage.error` + reject）；401 → 刷新一次 → 重试；刷新失败 → 登出 → `/login`。模块文件导出强类型函数，TS 类型镜像后端 VO（`types/`）。

---

## 11. 前端设计规范（消 AI 味）

采用 [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) 的 **Cal.com DESIGN.md**（Stitch 格式 9 节：视觉调性/配色/字体层级/组件样式/Layout/阴影/Do's & Don'ts/响应式/Agent 提示词）作为前端视觉契约。

**落地方式**：
1. **S0** 从 awesome-design-md 仓库取 Cal.com 的 `DESIGN.md`（实现时确认仓库内路径），放进 `frontend/DESIGN.md`。
2. **Element Plus 主题映射到 Cal.com tokens**：在 `frontend/src/styles/theme.ts`（或 SCSS 变量）覆盖 `--el-color-primary` 及色阶、字体族、圆角 `--el-border-radius-*`、阴影、间距，让组件库整体换皮为 Cal.com 调性（干净中性、浅色、专业克制），而非 Element Plus 默认蓝。
3. **每个 view 按 DESIGN.md 的「Component Stylings / Layout / Do's & Don'ts」实现**：卡片、按钮状态、留白节奏、栅格、字号层级，做到品牌级一致性。
4. 实现前端页面前，agent 必须先读 `frontend/DESIGN.md`；评审页面时对照 Do's & Don'ts 自检。

> Cal.com 选择理由：开源预约平台，主题最契合（预约≈排期）；干净中性浅色，学生+管理员都舒服；信息密度适中，表格/表单/日历是它的主场。

---

## 12. 测试策略

### 12.1 后端

- **单测**（JUnit5 + Mockito）：
  - `RecommendationService`：mock 用户历史 → 断言排序 + 理由 + 冷启动降级（新用户→热度）。
  - Redis 锁 acquire/release：mock `RedissonClient` → 断言 `tryLock` 调用、失败抛 `RESERVATION_CONFLICT`、`finally` 中 `unlock`、Redis 异常走 fail-open。
  - WS 广播：mock `SimpMessagingTemplate` → 断言 `convertAndSendToUser` 用对 userId/payload。
  - 驾驶舱聚合：mock mapper → 断言 VO 装配 + 角色 scope。
- **集成**（Testcontainers-redis，Docker 现已健康 29.2.0）：
  - **Redis 锁并发 IT**：多线程并发对同设备同天建预约 → 断言恰好一个成功、其余 `RESERVATION_CONFLICT`、且锁释放无泄漏（事后可再约）。复用 Phase1 并发 IT 的线程模型。
  - 驾驶舱 overview IT：灌种子 → 按角色 scope 断言指标。
- **回归**：Phase1 的 39 测试零回归。

### 12.2 前端

- **关键纯逻辑单测**（Vitest）：`hasPerm/hasRole`、路由守卫判定、分数/格式化。不做全组件覆盖（YAGNI）。
- **每 slice 手动冒烟**：登录 → 角色流程 → 亮点生效。

---

## 13. 配置与基础设施

- `application-dev.yml`：datasource 改连容器 mysql（localhost:3306，root/123456，端口映射不变）；新增：
  - `spring.data.redis.*`（host/port/无密码）。
  - `lab.recommend.weights.{alpha,beta,gamma,delta,epsilon}`、`lab.recommend.cache-ttl`。
  - `lab.dashboard.cache-ttl`。
  - `lab.lock.wait-seconds: 3`。
- Redisson：默认 auto-config 读 `spring.data.redis`；或显式 `redisson.yml`（S0 定）。
- WebSocket：`WebSocketConfig` + `AuthChannelInterceptor`（仅 `/ws` 端点放行，CONNECT 帧鉴权）。
- Flyway：schema 变更走 **V4+** 新迁移（本阶段预计无需改 schema——推荐/驾驶舱均复用现有表；若驾驶舱热力需要物化视图/汇总表再议）。

---

## 14. 完成定义（Definition of Done）

1. `docker compose up -d` 起全部中间件；后端 + 前端 dev 都能起、登录通。
2. **S1**：三角色各自全流程在 UI 跑通（浏览→预约→审批→签到→归还→通知→报修）。
3. **锁片**：Redis 锁并发 IT 绿 + 可脚本演示跨进程防超约（双层防线）。
4. **推送片**：两浏览器实时演示（管理员审批 → 学生端 toast）。
5. **驾驶舱片**：三角色 ECharts 图表正确渲染（饼/折线/柱/热力），数据按 scope 正确。
6. **推荐片**：学生登录见个性化推荐 + 理由；新用户退化为热度推荐。
7. 后端单测 + 集成全绿，Phase1 的 39 测试零回归。
8. 前端关键纯逻辑单测 + 每 slice 冒烟；`pnpm build` 成功。
9. Knife4j 含全部新接口（推荐/驾驶舱 overview/me）；WS 连接说明在 doc。
10. 前端视觉对照 Cal.com DESIGN.md 的 Do's & Don'ts 自检通过（无 AI 味）。

---

## 15. 已确认决策（Resolved）

1. **交付结构**：原阶段2+3 合并为一个连续工程，纵切功能片（S0→S5），一份 spec + 一份分片 plan。
2. **RabbitMQ**：compose 预装容器，代码不接入；真接入留阶段4。
3. **MySQL**：容器化（compose），Flyway 重建 + V2 灌种子；本地现有库不迁移。
4. **Redis**：compose 跑 redis:7；测试用 Testcontainers-redis（Docker 已健康）。
5. **锁实现**：Redisson `RLock` + `MultiLock(device,date)` + `tryLock(3s,-1)` 看门狗 + fail-open；DB 唯一索引兜底（双层防线）。
6. **推荐算法**：混合启发式打分（类目/实验室亲和 + 热度 + 标签 − 已用惩罚）+ 可解释理由 + 冷启动热度降级 + Redis 缓存。
7. **WebSocket**：STOMP+SockJS，**握手期 query token 鉴权**（`WsAuthHandshakeInterceptor` + `JwtHandshakeHandler` 设会话 Principal → 注册 SimpUserRegistry → `convertAndSendToUser` 可达）。【实现修订：原计划 CONNECT 帧头鉴权因 registry 不注册而改，见 §7.2】
8. **驾驶舱**：每角色聚合端点（overview/me），vue-echarts，重查询 Redis 缓存。
9. **前端视觉**：awesome-design-md 的 **Cal.com DESIGN.md** 作为视觉契约，Element Plus 主题映射其 tokens。
10. **前端栈**：Vite+Vue3+TS+Element Plus+Pinia(持久化)+Vue Router+axios+ECharts+@stomp/stompjs+sockjs-client+dayjs，pnpm。
