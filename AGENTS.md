# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

高校实验室设备预约系统的毕业设计 / 生产级课程项目。两层结构:

- **后端**: Spring Boot 3.2.5 (Java 17) + MyBatis-Plus 3.5.5 + Spring Security + JWT + Redisson + Flyway + WebSocket/STOMP
- **前端**: Vue 3 + Vite 8 + TypeScript + Element Plus + Pinia + ECharts + SockJS/STOMP
- **数据库**: MySQL 8.0(主数据) + Redis 7(分布式锁/缓存/会话外的实时通信兜底)
- **包名**: `com.lab.reservation`(根) → 模块按 controller / service / mapper / entity / dto / vo / config / security / aspect / task / mq 切分
- **前端入口**: `frontend/src/main.ts`,生产打包至 `frontend/dist`
- **API 基础路径**: `server.servlet.context-path=/api`(所有 controller 路由不带 `/api` 前缀)

## 命令

### 后端

```bash
# 编译 + 运行测试(默认 Surefire 匹配 *Test.java 和 *IT.java,加 -DskipTests 跳过)
mvn test
mvn package -DskipTests

# 跑单个测试类
mvn test -Dtest=ReservationConcurrencyIT
mvn test -Dtest=ReservationLifecycleTest

# 跑单个测试方法
mvn test -Dtest=ReservationConcurrencyIT#方法名

# 起服务(默认 dev profile 读 application-dev.yml,连 localhost:3306 mysql 和 :6379 redis)
mvn spring-boot:run

# JDK 17 环境下,Windows 一键跑 ReservationConcurrencyIT(reference 实现)
run-test.cmd
```

### 前端

```bash
cd frontend
pnpm install        # 注意 pnpm 不是 npm;corepack 已锁 pnpm@9
pnpm dev            # vite dev server @ http://localhost:5173,代理 /api /ws → :8080
pnpm build          # vue-tsc 类型检查 + vite build
pnpm preview
pnpm test           # vitest 单元测试
pnpm test:watch
```

### Docker / 一键起 mysql+redis

```bash
# 本地开发依赖(docker-compose.yml 只有 mysql + redis)
docker compose up -d

# 生产部署(详见 DEPLOY-WITH-WEBHOOK.md):含 app + frontend + mysql + redis,顶级 name=labprod
docker compose -f docker-compose.prod.yml up -d --build

# 后端 Dockerfile 使用 .mvn/docker-settings.xml(阿里云镜像)解决 Docker BuildKit 拉 Maven Central 超时
```

## 测试策略

- `src/test/java/.../*Test.java`: 纯单元测试(JUnit 5 + Mockito + Spring slice),无外部依赖
- `*IT.java`: 集成测试,后缀 InTest 需 MySQL;**并发 IT**(`ReservationConcurrencyIT`、`RedisLockConcurrencyIT`)通过 Testcontainers 启 MySQL,需 Docker desktop running(`run-test.cmd` 已设好 `TESTCONTAINERS_RYUK_DISABLED=true` 与 `-Ddocker.host`)
- Surefire 已配 `-Dnet.bytebuddy.experimental=true`(JDK 25 + Mockito 5.x 兼容)
- 前端 vitest 配 jsdom + `@vue/test-utils`

## 关键架构(必读)

### 1. 后端分层

```
controller/   ← @RestController,接 HTTP
service/      ← interface + impl/;事务边界在 Service 层(@Transactional)
mapper/       ← MyBatis-Plus BaseMapper 接口; XML 在 src/main/resources/mapper/
entity/       ← 数据库表(extends BaseEntity 含 createTime/updateTime)
dto/          ← 入参; vo/ ← 出参
config/       ← MyBatisPlusConfig、SecurityConfig、Redis/Redisson、WebSocketConfig 等
security/     ← JWT 过滤器、UserDetails、auth/ws 子包
aspect/       ← OperationLogAspect(@Log 注解环绕,异步写 operation_log,不要在类内 this 调 @Async 方法)
task/         ← 后台 @Scheduled / @PostConstruct(LocalTimeoutScheduler 见下)
mq/           ← 通知相关(RabbitMQ 已废弃,见下"通知与超时")
exception/    ← BusinessException + GlobalExceptionHandler
init/         ← DataInitializer(种子数据)
common/result ← Result<T> + ResultCode(控制器统一返回结构)
```

### 2. 预约状态机(规格 §6.3)

`PENDING →(审批)→ APPROVED →(签到)→ IN_USE →(归还)→ COMPLETED`,任意非终态可 → `CANCELLED`(原因: USER / TIMEOUT / ADMIN),`APPROVED/IN_USE` 可被管理员 → `VIOLATED`,`APPROVED` → `NO_SHOW`。

所有转换都在 `ReservationServiceImpl` 里集中,**不要**在 controller 直接改 status。

### 3. 并发防超约(关键)

`ReservationLock` 用 Redisson `MultiLock` 对 `(deviceId, date)` 加锁,**信号槽**(slot)是 `lab.slot.minutes`(默认 15 分钟,1 槽 = 15min)。锁是 fail-open:Redis 不可用 → 返回 `null` 让调用方走 DB 唯一索引兜底(双重保险)。

`SlotCalculatorService` + `SlotKey(deviceId, date, slotIndex)` 是冲突检测的最小单位。

### 4. 通知与超时(原 RabbitMQ 方案已废弃)

- 通知:**同进程异步**,`NotificationProducer.notify()` 事务中通过 `TransactionSynchronization.afterCommit` 延迟投递,`NotificationDispatcher` 异步写库 + 推 STOMP(`/user/{userId}/queue/notifications`)。每条消息带 UUID `msgId` 幂等键。
- 超时:`ReservationTimeoutProducer` 在 approve 落库时往 `pending_timeout_task` 表插一行(`execute_at = startTime + grace`),`LocalTimeoutScheduler` 每 5s(`@Scheduled fixedDelayString`)扫描到点任务,调 `ReservationService.markTimeoutCancelled`,失败 attempts+1、5 次后置 FAILED。重启时 `@PostConstruct scanOnStartup` 兜底。单实例假设,横向扩展需 ShedLock 或 MySQL `FOR UPDATE SKIP LOCKED`。

### 5. 安全(JWT + STOMP + 角色权限)

- 无状态 REST:JwtAuthenticationFilter → SecurityContextHolder;`SecurityConfig.authenticationEntryPoint` 强制返回 **401 JSON** 而非 Spring 6 默认 403,以便前端拦截器触发 refresh
- 角色:RBAC 三表(`sys_user`/`sys_role`/`sys_permission`) + 用户-角色 / 角色-权限多对多;`@PreAuthorize("hasAuthority('device:approve')")` 用 `permission code` 鉴权,**不是** role 名
- STOMP 握手鉴权:浏览器 WS 无法加 header,token 经 query `?token=...` → `WsAuthHandshakeInterceptor` 解析 → `JwtHandshakeHandler` 注入 Principal → `convertAndSendToUser(userId, ...)`
- Spring Security `requestMatchers` 写路径**不带 `/api` 前缀**(容器自动剥离)

### 6. 切面 / 日志 / Redis

- `OperationLogAspect` + `@Log` 注解:对 controller 方法环绕,**耗时写 finally**(异常也记);序列化+insert 委托给独立的 `OperationLogWriter` bean 才走 Spring 代理 `@Async` 真正异步
- Redisson:RedissonClient bean 见 `RedissonConfig`,`@Lock` 等场景用 `RLock`
- `@EnableAsync` 已在 `ReservationApplication`,`@Async` 必须跨 bean 调才生效

### 7. 数据库迁移

Flyway,迁移脚本在 `src/main/resources/db/migration/`:

- V1__init_schema.sql(基线),V2__seed_data.sql,后续按 V3..V6 顺序
- 改表结构:新增 V7__xxx.sql,**禁止**改老的 V__*.sql(已有环境就跳过)
- `application-dev.yml` 启 `flyway.baseline-on-migrate=true`,既能从 V1 也兼容已有库

### 8. 前端架构

```
src/
  api/       ← axios 实例 + request.ts(响应拦截:401 → 跳登录)
  stores/    ← Pinia(pinia-plugin-persistedstate 持久化 user)
  router/    ← vue-router + 自定义 guard.ts(角色/未登录)
  views/     ← 按业务模块(login/、dashboard/、device/、reservation/、approval/、notification/、repair/、recommendation/、user/)
  components/ui/   ← 自研深色风格基础组件(GlowCard/GradientButton/StatCard 等)
  components/charts/ ← ECharts 封装(BaseChart + BarWidget/LineWidget/PieWidget/HeatmapWidget)
  layouts/   ← MainLayout
  directives/、composables/、styles/、utils/、types/
  assets/
```

要点:
- Vite `optimizeDeps.esbuildOptions.define: { global: 'globalThis' }` 解决 sockjs-client@1.6.1 顶层 `global` 引用报错
- `VITE_WS_BASE` 来自 `.env.development` / `.env.production`,SockJS + STOMP 客户端连后端 `/api/ws`(经 dev proxy / 生产 nginx 反代)
- API 错误码统一 `{ code, msg, data }`,Result.fail 时 `code != 200`

### 9. 部署

详见 **`DEPLOY-WITH-WEBHOOK.md`**(36KB)。要点:

- GitHub Webhook → 服务器 webhook 进程(HMAC 验签 + 仅响应 `ref=refs/heads/main`)→ `deploy.sh` 做 `flock` 单飞 + `git pull` + `docker compose -f docker-compose.prod.yml up -d --build`
- **关键**:生产 compose 文件是 `docker-compose.prod.yml`(顶级 `name: labprod`,**不要**碰根目录 `docker-compose.yml`,那是 dev-only 的 mysql+redis)
- 宿主机只需 `docker`(用 docker-ce 仓库装,带 compose v2 插件);JDK/Maven/Node 都在镜像里
- 4GB 内存分配: mysql 512M / redis 128M / app 768M / frontend 64M

## JDK / 工具链坑点

- **`pom.xml` 强制 Lombok 1.18.42**(Spring Boot 3.2.5 自带的 1.18.32 不支持 JDK 25,会导致 `@Slf4j` / `@Data` 注解处理失效 → 启动 ClassNotFoundException 雪崩)
- 显式声明 `<annotationProcessorPaths>` 绕过 Maven 3.9 + JDK 25 上 `AnnotationProcessorHider` 自动探测失败
- Surefire `-Dnet.bytebuddy.experimental=true` 兼容 JDK 25 字节码
- 后端 Dockerfile 用 `.mvn/docker-settings.xml` 注入阿里云镜像,BuildKit 直连 Maven Central 会超时
- 没有 `.cursor/` / `.cursorrules` / `.github/`,无额外规则文件

## 配置文件层次

`src/main/resources/`:
- `application.yml`: 默认 + 端口(8080) + context-path(/api) + jackson 时区(Asia/Shanghai)
- `application-dev.yml`: 本地 mysql/redis + flyway 启用 + 业务参数(`lab.lock.wait-seconds` / `lab.recommend.weights` / `lab.task.timeout.*`)
- `application-prod.yml`: 生产(端口/日志级别通常用容器环境变量覆盖)

`frontend/.env.{development,production}` 控制 `VITE_WS_BASE` 等。
