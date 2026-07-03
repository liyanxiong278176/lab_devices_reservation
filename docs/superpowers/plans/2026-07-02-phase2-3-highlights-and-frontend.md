# 阶段2+3 实现计划：后端四大亮点 + Vue3 三端前端（纵切功能片）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成的阶段1后端上叠加 Redis 分布式锁、智能推荐、WebSocket 推送、ECharts 驾驶舱四大亮点，并构建 Vue3 三端前端，按 S0–S5 纵切功能片依次交付、每片可演示。

**Architecture:** 前后端分离单体。后端 Spring Boot 3.2.5（新增 Redisson/WebSocket）；前端 Vite+Vue3+TS+Element Plus（视觉基准 Cal.com DESIGN.md）。中间件 mysql+redis+rabbitmq 由 `docker-compose.yml` 一键起。通知走"DB 持久化 + WebSocket 实时推送"双写；预约防超约走"Redisson 锁 + DB 唯一索引"双层防线。

**Tech Stack:** Java 17 / Spring Boot 3.2.5 / MyBatis-Plus / Redisson 3.31.0 / STOMP+SockJS / Testcontainers-redis；Vite 5 / Vue 3.4 / TS 5.4 / Element Plus 2.7 / Pinia / Vue Router / axios / ECharts / @stomp/stompjs / pnpm。

**关键环境（务必遵守）：**
- Maven 用 **JDK 17**：`MVN="JAVA_HOME=/d/jdk17/jdk-17.0.13+11 PATH=/d/jdk17/jdk-17.0.13+11/bin:$PATH mvn"`（下文命令以 `mvn17` 代指此前缀）。
- MySQL/Redis/RabbitMQ 由 compose 起（Task 1）；测试用 Testcontainers-redis（Docker 29.2.0 已健康）。
- Flyway V1–V3 已应用且**不可改**；schema 变更走 V4+（本阶段预计无需改 schema）。
- 包结构沿用经典平铺 MVC（`controller/service(+impl)/mapper/entity/dto/vo`），前端独立 `frontend/` 工程。

**上游 spec：** `docs/superpowers/specs/2026-07-02-phase2-3-highlights-and-frontend-design.md`

---

## 文件结构（File Map）

### 后端新增/修改

| 文件 | 责任 | 动作 |
|---|---|---|
| `docker-compose.yml`（仓库根） | mysql+redis+rabbitmq 一键起 | 新建 |
| `pom.xml` | 加 websocket、redisson、testcontainers-core | 修改 |
| `src/main/resources/application-dev.yml` | datasource→容器、redis、锁/推荐/驾驶舱配置项 | 修改 |
| `src/main/java/com/lab/reservation/config/RedissonConfig.java` | RedissonClient bean（读 spring.data.redis） | 新建 |
| `.../config/WebSocketConfig.java` | @EnableWebSocketMessageBroker、/ws+SockJS、broker 前缀 | 新建 |
| `.../security/ws/AuthChannelInterceptor.java` | 拦 STOMP CONNECT，JWT→Principal(userId) | 新建 |
| `.../service/impl/ReservationServiceImpl.java` | create() 加 Redisson MultiLock 双层防线 | 修改 |
| `.../service/impl/NotificationServiceImpl.java` | notify() 双写 DB+WS（convertAndSendToUser） | 修改 |
| `.../service/RecommendationService.java` + impl | 混合启发式打分+理由+冷启动+缓存 | 新建 |
| `.../controller/RecommendationController.java` | GET /recommendations | 新建 |
| `.../service/DashboardService.java`（已存在）+ impl | 富指标+角色聚合 overview/me | 修改 |
| `.../controller/DashboardController.java`（已存在） | +/overview +/me | 修改 |
| `.../dto/recommendation/`、`.../vo/recommendation/`、`.../vo/dashboard/` | DTO/VO | 新建 |
| `.../mapper/ReservationItemMapper.java` / `ReservationMapper.java` | 新增聚合查询（利用率/热力/热度/类目） | 修改 |
| `src/main/resources/mapper/*.xml`（若用 XML） | 聚合 SQL | 新建/修改 |
| `src/test/...` | 锁/推荐/WS/驾驶舱单测 + Redis 锁并发 IT | 新建 |
| `SecurityConfig.java` | /ws/** permitAll（鉴权在 CONNECT 帧） | 修改 |

### 前端新增（`frontend/`，全新 Vite 工程）

| 文件 | 责任 |
|---|---|
| `frontend/DESIGN.md` | Cal.com 视觉契约（从 awesome-design-md 仓库取） |
| `frontend/src/main.ts` | createApp + ElementPlus + Pinia(持久化) + Router |
| `frontend/src/styles/theme.ts` + `index.scss` | Element Plus 主题变量映射到 Cal.com tokens |
| `frontend/src/api/request.ts` | axios 实例 + 拦截器(token/Result 解包/401 刷新) |
| `frontend/src/api/{auth,device,reservation,approval,repair,notification,user,dashboard,recommendation}.ts` | 各模块接口 |
| `frontend/src/stores/{user,notification,app}.ts` | Pinia 状态 |
| `frontend/src/router/{index.ts,guard.ts}` | history 模式 + token/角色守卫 |
| `frontend/src/layouts/MainLayout.vue` | 顶栏(未读角标)+侧栏(角色菜单)+router-view |
| `frontend/src/views/**` | login/dashboard/device/reservation/approval/repair/user/recommendation |
| `frontend/src/composables/{useWebSocket,useEcharts,usePermission}.ts` | 组合式逻辑 |
| `frontend/src/directives/permission.ts` | v-permission(按 perm_code) |
| `frontend/src/types/**` | 与后端 VO 对齐的 TS 类型 |

---

# Slice S0 — 基建

## Task 1: docker-compose 中间件一键起

**Files:**
- Create: `docker-compose.yml`
- Modify: `src/main/resources/application-dev.yml`

- [ ] **Step 1: 写 docker-compose.yml**

```yaml
# docker-compose.yml（仓库根）
services:
  mysql:
    image: mysql:8.0
    container_name: lab-mysql
    environment:
      MYSQL_ROOT_PASSWORD: "123456"
      MYSQL_DATABASE: lab_reservation
      TZ: Asia/Shanghai
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    ports: ["3306:3306"]
    volumes: ["mysql_data:/var/lib/mysql"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-p123456"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:7-alpine
    container_name: lab-redis
    ports: ["6379:6379"]
    volumes: ["redis_data:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  rabbitmq:
    image: rabbitmq:3.13-management
    container_name: lab-rabbitmq
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    ports: ["5672:5672", "15672:15672"]   # 5672 AMQP / 15672 管理界面
    volumes: ["rabbitmq_data:/var/lib/rabbitmq"]

volumes:
  mysql_data:
  redis_data:
  rabbitmq_data:
```

- [ ] **Step 2: 改 application-dev.yml 连容器 redis**

在 `application-dev.yml` 的 `spring:` 下新增（datasource 的 url 端口已是 3306，容器映射一致，**无需改 url**；Flyway 会对全新容器库从 V1 跑起重建）：

```yaml
  data:
    redis:
      host: localhost
      port: 6379
      database: 0
      # 无密码
lab:
  slot: { minutes: 15, work-start: "08:00", work-end: "22:00", check-in-grace-minutes: 0 }
  lock: { wait-seconds: 3 }
  recommend:
    weights: { alpha: 0.4, beta: 0.2, gamma: 0.25, delta: 0.1, epsilon: 0.3 }
    cache-ttl-minutes: 5
  dashboard: { cache-ttl-minutes: 5 }
```

- [ ] **Step 3: 起中间件 + 验证**

Run: `docker compose up -d`
Expected: 三个容器 Up；`docker compose ps` 三者 healthy。
Run: `docker exec lab-redis redis-cli ping` → `PONG`
Run: `docker exec lab-mysql mysql -uroot -p123456 -e "SHOW DATABASES" | grep lab_reservation`

- [ ] **Step 4: 启动后端验证 Flyway 在容器库重建 + Redis 连通**

Run: `mvn17 spring-boot:run`
Expected: 日志见 Flyway `Successfully applied V1/V2/V3 to schema`（容器新库）、`Redis` 连接健康、无启动错误。Knife4j `http://localhost:8080/api/doc.html` 可开。用 `admin/admin123` 登录验证种子数据在。

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml src/main/resources/application-dev.yml
git commit -m "feat(infra): docker-compose(mysql+redis+rabbitmq)+dev配置连容器"
```

---

## Task 2: 后端加 WebSocket + Redisson 依赖

**Files:**
- Modify: `pom.xml`

- [ ] **Step 1: 加依赖**

在 `pom.xml` `<dependencies>` 中追加：

```xml
<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-websocket</artifactId></dependency>
<dependency>
    <groupId>org.redisson</groupId>
    <artifactId>redisson-spring-boot-starter</artifactId>
    <version>3.31.0</version>
</dependency>
<!-- 测试：Testcontainers GenericContainer 跑 redis（testcontainers.version 属性已在 pom 存在=1.19.7，core 需显式加） -->
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>testcontainers</artifactId>
    <version>${testcontainers.version}</version>
    <scope>test</scope>
</dependency>
```

并在 `<properties>` 加 `<redisson.version>3.31.0</redisson.version>`（可选，上面已硬编版本）。

- [ ] **Step 2: 验证编译**

Run: `mvn17 -q -DskipTests compile`
Expected: BUILD SUCCESS（若 redisson 3.31.0 与 SB 3.2.5 有冲突，降到 3.27.2 重试）。

- [ ] **Step 3: Commit**

```bash
git add pom.xml
git commit -m "feat(deps): 加websocket+redisson+testcontainers-core依赖"
```

---

## Task 3: RedissonConfig（确定性 bean）

**Files:**
- Create: `src/main/java/com/lab/reservation/config/RedissonConfig.java`

- [ ] **Step 1: 写 RedissonConfig**

```java
package com.lab.reservation.config;

import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 显式构建 RedissonClient（避免 starter 自动配置读错 redis 前缀）。 */
@Configuration
public class RedissonConfig {

    @Value("${spring.data.redis.host:localhost}") private String host;
    @Value("${spring.data.redis.port:6379}") private int port;
    @Value("${spring.data.redis.password:}") private String password;
    @Value("${spring.data.redis.database:0}") private int database;

    @Bean(destroyMethod = "shutdown")
    public RedissonClient redissonClient() {
        Config cfg = new Config();
        var single = cfg.useSingleServer()
                .setAddress("redis://" + host + ":" + port)
                .setDatabase(database);
        if (password != null && !password.isBlank()) {
            single.setPassword(password);
        }
        return Redisson.create(cfg);
    }
}
```

- [ ] **Step 2: 验证启动注入成功**

Run: `mvn17 spring-boot:run`
Expected: 启动无错；RedissonClient bean 存在（日志无 NoSuchBean）。

- [ ] **Step 3: Commit**

```bash
git add src/main/java/com/lab/reservation/config/RedissonConfig.java
git commit -m "feat(config): RedissonClient显式bean(读spring.data.redis)"
```

---

## Task 4: 前端工程脚手架 + Cal.com DESIGN.md

**Files:**
- Create: `frontend/**`（整个 Vite 工程）

- [ ] **Step 1: 创建 Vite 工程**

Run（仓库根）: `pnpm create vite frontend --template vue-ts`
然后 `cd frontend && pnpm install`

- [ ] **Step 2: 装依赖**

Run:
```bash
pnpm add vue-router pinia pinia-plugin-persistedstate axios element-plus @element-plus/icons-vue echarts vue-echarts dayjs @stomp/stompjs sockjs-client
pnpm add -D @types/sockjs-client sass vitest @vue/test-utils jsdom
```

- [ ] **Step 3: 取 Cal.com DESIGN.md**

从 https://github.com/VoltAgent/awesome-design-md 仓库找到 Cal.com 目录（`websites/cal.com/` 或 `cal-com/`，实现时确认），将其 `DESIGN.md` 复制到 `frontend/DESIGN.md`。读一遍确认含 9 节（配色/字体/组件/Layout/阴影/Do's & Don'ts 等）。

- [ ] **Step 4: vite 代理 + tsconfig**

`frontend/vite.config.ts`：
```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
      '/ws':  { target: 'http://localhost:8080', ws: true, changeOrigin: true },
    },
  },
})
```
`tsconfig.json` 加 `"@/*": ["src/*"]` 路径映射、`"types": ["vitest/globals"]`。

- [ ] **Step 5: 验证 dev server 起**

Run: `pnpm dev` → 访问 `http://localhost:5173` 见默认页。

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(fe): Vue3+TS工程脚手架+依赖+Cal.com DESIGN.md+vite代理"
```

---

## Task 5: Cal.com 主题层（Element Plus 换皮）

**Files:**
- Create: `frontend/src/styles/theme.scss`, `frontend/src/main.ts`（注册 ElementPlus + 图标 + 持久化 Pinia）

- [ ] **Step 1: 读 DESIGN.md 提取 tokens，写 theme.scss**

读 `frontend/DESIGN.md`，把 Cal.com 的主色/字体/圆角/阴影映射为 Element Plus CSS 变量覆盖。`frontend/src/styles/theme.scss`（数值据 DESIGN.md 实际值替换 `#xxx`）：

```scss
:root {
  /* Cal.com 主色映射到 Element Plus */
  --el-color-primary: #292929;          // Cal.com 用近黑作主操作色（按 DESIGN.md 实际替换）
  --el-color-primary-light-3: #4d4d4d;
  --el-color-primary-light-5: #707070;
  --el-color-primary-light-7: #a6a6a6;
  --el-color-primary-light-8: #c4c4c4;
  --el-color-primary-light-9: #e6e6e6;
  --el-color-primary-dark-2: #1a1a1a;
  --el-border-radius-base: 8px;         // Cal.com 圆角
  --el-font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --el-box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  --el-bg-color: #ffffff;
  --el-bg-color-page: #fafafa;
  --el-text-color-primary: #292929;
}
body { background: var(--el-bg-color-page); }
```

> 实现时**严格按 DESIGN.md 的实际 hex 值**填，不要照搬上面的占位值。

- [ ] **Step 2: main.ts 注册全家桶**

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import './styles/theme.scss'
import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
for (const [k, v] of Object.entries(ElementPlusIconsVue)) app.component(k, v as any)
app.use(pinia).use(router).use(ElementPlus)
app.mount('#app')
```

- [ ] **Step 3: 验证主题生效**

在 App.vue 放一个 `<el-button type="primary">测试</el-button>`，`pnpm dev` 看按钮颜色=Cal.com 主色、圆角/字体符合 DESIGN.md。对照 DESIGN.md 的 Do's & Don'ts 自检。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/theme.scss frontend/src/main.ts frontend/src/App.vue
git commit -m "feat(fe): Cal.com主题层(Element Plus CSS变量映射)+全家桶注册"
```

---

## Task 6: axios 封装 + userStore

**Files:**
- Create: `frontend/src/api/request.ts`, `frontend/src/api/auth.ts`, `frontend/src/stores/user.ts`, `frontend/src/stores/app.ts`

- [ ] **Step 1: request.ts（拦截器：token 注入 / Result 解包 / 401 刷新）**

```ts
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const service: AxiosInstance = axios.create({ baseURL: '/api', timeout: 15000 })

service.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  const u = useUserStore()
  if (u.accessToken) cfg.headers.set('Authorization', `Bearer ${u.accessToken}`)
  return cfg
})

let refreshing = false
service.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 200) return body.data         // 解包 Result.data
      ElMessage.error(body.msg || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  async (err) => {
    const u = useUserStore()
    if (err.response?.status === 401 && !err.config.__retried) {
      err.config.__retried = true
      if (!refreshing) {
        refreshing = true
        try { await u.refresh(); refreshing = false; return service(err.config) }
        catch { refreshing = false; u.logout(); router.push('/login'); return Promise.reject(err) }
      }
    }
    const msg = err.response?.data?.msg || err.message
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)
export default service
```

- [ ] **Step 2: api/auth.ts**

```ts
import request from './request'
export const login = (data: { username: string; password: string }) =>
  request.post('/auth/login', data)
// 后端 AuthController.refresh 用 @RequestParam（query/form 参数），非 JSON body
export const refresh = (refreshToken: string) =>
  request.post('/auth/refresh', null, { params: { refreshToken } })
export const getMe = () => request.get('/auth/me')
```

- [ ] **Step 3: stores/user.ts（持久化 token）**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const accessToken = ref<string>('')
  const refreshToken = ref<string>('')
  const userId = ref<number | null>(null)
  const username = ref<string>('')
  const realName = ref<string>('')
  const roles = ref<string[]>([])
  const permissions = ref<string[]>([])

  async function login(payload: { username: string; password: string }) {
    const data: any = await authApi.login(payload)
    accessToken.value = data.accessToken
    refreshToken.value = data.refreshToken
    userId.value = data.userInfo?.id
    username.value = data.userInfo?.username
    realName.value = data.userInfo?.realName
    roles.value = data.roles || []
    permissions.value = data.permissions || []
  }
  async function refresh() {
    const data: any = await authApi.refresh(refreshToken.value)
    accessToken.value = data.accessToken
  }
  async function fetchMe() {
    const me: any = await authApi.getMe()
    userId.value = me.id; username.value = me.username; realName.value = me.realName
    roles.value = me.roles || []; permissions.value = me.permissions || []
  }
  function logout() {
    accessToken.value = ''; refreshToken.value = ''
    userId.value = null; username.value = ''; realName.value = ''
    roles.value = []; permissions.value = []
  }
  const hasPerm = (code: string) => permissions.value.includes(code)
  const hasRole = (r: string) => roles.value.includes(r)

  return { accessToken, refreshToken, userId, username, realName, roles, permissions,
           login, refresh, fetchMe, logout, hasPerm, hasRole }
}, { persist: { key: 'lab-user', pick: ['accessToken', 'refreshToken'] } })
```

- [ ] **Step 4: 验证（需先有 router，临时跳过到 Task 7 联调）**

先确保 `pnpm build` 不报类型错。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/request.ts frontend/src/api/auth.ts frontend/src/stores/user.ts frontend/src/stores/app.ts
git commit -m "feat(fe): axios拦截器(token/Result解包/401刷新)+userStore持久化"
```

---

## Task 7: 路由 + 守卫 + MainLayout + 登录页（S0 联调闭环）

**Files:**
- Create: `frontend/src/router/index.ts`, `frontend/src/router/guard.ts`, `frontend/src/layouts/MainLayout.vue`, `frontend/src/views/login/Login.vue`

- [ ] **Step 1: router/index.ts（路由 + meta.roles，懒加载）**

```ts
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { guard } from './guard'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/login/Login.vue'), meta: { public: true } },
  { path: '/', component: () => import('@/layouts/MainLayout.vue'), redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/dashboard/Index.vue'),
        meta: { title: '驾驶舱', icon: 'Odometer' } },
      // S1/S2/S5 页面在各自 slice 追加，均带 meta: { roles?: [...] }
    ] },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]
const router = createRouter({ history: createWebHistory(), routes })
router.beforeEach(guard)
export default router
```

- [ ] **Step 2: router/guard.ts**

```ts
import type { NavigationGuardWithThis } from 'vue-router'
import { useUserStore } from '@/stores/user'

export const guard: NavigationGuardWithThis<undefined> = (to) => {
  const u = useUserStore()
  if (to.meta.public) return true
  if (!u.accessToken) return { path: '/login', query: { redirect: to.fullPath } }
  const need = to.meta.roles as string[] | undefined
  if (need && need.length && !need.some((r) => u.roles.includes(r))) return false // 403：留步
  return true
}
```

- [ ] **Step 3: views/login/Login.vue（按 Cal.com DESIGN.md 实现，简洁居中卡片）**

按 `frontend/DESIGN.md` 的 Layout/Component 规则：居中卡片、标题用 DESIGN.md 字体层级、主按钮 Cal.com 主色。关键逻辑：

```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

const form = reactive({ username: 'admin', password: 'admin123' })
const loading = ref(false)
const router = useRouter(); const route = useRoute(); const u = useUserStore()

async function onSubmit() {
  loading.value = true
  try {
    await u.login(form)
    await u.fetchMe()
    ElMessage.success('登录成功')
    router.push((route.query.redirect as string) || '/dashboard')
  } finally { loading.value = false }
}
</script>
```
（模板用 `el-form` + `el-input` + `el-button`，样式遵循 DESIGN.md。）

- [ ] **Step 4: layouts/MainLayout.vue（侧栏动态菜单 + 顶栏 + router-view）**

侧栏由路由表 `meta.title/icon` 动态渲染（后续按角色过滤）；顶栏右侧放用户名 + 登出。骨架：

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
const router = useRouter(); const u = useUserStore()
const menus = router.getRoutes()
  .filter(r => r.meta?.title && (r.children || r.meta.roles ? true : true))
  // 角色过滤在 S1 完善（按 meta.roles ∩ u.roles）
function logout() { u.logout(); router.push('/login') }
</script>
<template>
  <el-container style="height:100vh">
    <el-aside width="220px"><!-- 侧栏菜单 --></el-aside>
    <el-container>
      <el-header><!-- 顶栏：标题 + 用户/登出 --></el-header>
      <el-main><router-view /></el-main>
    </el-container>
  </el-container>
</template>
```

- [ ] **Step 5: 验证端到端登录**

`pnpm dev`（后端已在跑）→ 访问 `http://localhost:5173` → 跳 `/login` → admin/admin123 登录 → 进 `/dashboard`（暂占位 `views/dashboard/Index.vue` 放个 "驾驶舱待 S4"）。DevTools 看 `Authorization` 头带上、响应 200。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/router frontend/src/layouts frontend/src/views/login frontend/src/views/dashboard/Index.vue
git commit -m "feat(fe): 路由+角色守卫+MainLayout+登录(S0联调闭环)"
```

---

# Slice S1 — 核心页对接（Phase1 API 前端化）

## Task 8: API 模块 + TS 类型

**Files:**
- Create: `frontend/src/api/{device,reservation,approval,repair,notification,user,dashboard}.ts`, `frontend/src/types/**`

- [ ] **Step 1: 各 api 模块**

每个文件导出对齐后端 §8 的函数。示例 `device.ts`：
```ts
import request from './request'
export interface DeviceQuery { page?: number; size?: number; keyword?: string; categoryId?: number; labId?: number; status?: string; needApproval?: number; minPrice?: number; maxPrice?: number }
export const searchDevices = (q: DeviceQuery) => request.get('/devices', { params: q })
export const getDevice = (id: number) => request.get(`/devices/${id}`)
export const deviceCalendar = (id: number, from: string, to: string) => request.get(`/devices/${id}/calendar`, { params: { from, to } })
export const createDevice = (data: any) => request.post('/devices', data)
export const updateDevice = (id: number, data: any) => request.put(`/devices/${id}`, data)
export const deleteDevice = (id: number) => request.delete(`/devices/${id}`)
export const patchDeviceStatus = (id: number, status: string) => request.patch(`/devices/${id}/status`, { status })
```
其余 `reservation.ts`(create/list-mine/detail/cancel/check-in/check-out)、`approval.ts`(pending/approve/reject/batch)、`repair.ts`(submit/mine/list/take/resolve/reject)、`notification.ts`(mine/read/read-all)、`user.ts`(CRUD/status)、`dashboard.ts`(summary 占位) 同理。`types/` 放与后端 VO 对齐的 interface。

- [ ] **Step 2: 验证类型**

Run: `pnpm build` → 无 TS 错。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api frontend/src/types
git commit -m "feat(fe): 各业务api模块+TS类型(对齐Phase1接口)"
```

---

## Task 9: 设备浏览/检索 + 详情日历 + 建预约 + 我的预约

**Files:**
- Create: `frontend/src/views/device/{Index,Detail}.vue`, `frontend/src/views/reservation/{Create,Mine,Detail}.vue`, `frontend/src/directives/permission.ts`, `frontend/src/composables/usePermission.ts`

- [ ] **Step 1: v-permission 指令 + usePermission**

`directives/permission.ts`：
```ts
import type { Directive } from 'vue'
import { useUserStore } from '@/stores/user'
export const vPermission: Directive<HTMLElement, string | string[]> = {
  mounted(el, binding) {
    const u = useUserStore()
    const codes = Array.isArray(binding.value) ? binding.value : [binding.value]
    if (!codes.some((c) => u.permissions.includes(c))) el.parentNode?.removeChild(el)
  },
}
```
`composables/usePermission.ts` 导出 `hasPerm/hasRole`（复用 userStore）。在 `main.ts` 注册指令 `app.directive('permission', vPermission)`。

- [ ] **Step 2: 设备列表页（检索 + 分页）**

`views/device/Index.vue`：顶部检索条（关键字/categoryId/labId/status/价格区间），`el-table` 展示，操作列"查看/预约"。按 DESIGN.md 表格样式（行高、对齐、状态用 `el-tag`）。

- [ ] **Step 3: 设备详情页 + 日历**

`views/device/Detail.vue`：设备信息卡 + 日历组件（可简化为：选日期 → 调 `deviceCalendar` → `el-table`/`el-timeline` 展示已占槽）+ "立即预约"按钮跳 Create。

- [ ] **Step 4: 建预约页**

`views/reservation/Create.vue`：选设备 + 时间范围（`el-date-picker` type=datetime 范围，步长对齐 15 分钟）+ purpose → 调 `createReservation`。成功后 `ElMessage` + 跳我的预约。

- [ ] **Step 5: 我的预约 + 详情**

`Mine.vue`：按状态 tab + 分页 + 取消按钮。`Detail.vue`：详情 + 状态流转展示。

- [ ] **Step 6: 验证（学生流）**

注册/用已有学生账号登录 → 浏览设备 → 看日历 → 建预约（自动通过/待审批）→ 我的预约见记录 → 取消成功。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/device frontend/src/views/reservation frontend/src/directives frontend/src/composables
git commit -m "feat(fe): 设备浏览/详情日历/建预约/我的预约+v-permission"
```

---

## Task 10: 审批 / 报修 / 用户管理 / 通知(轮询) / 菜单角色过滤

**Files:**
- Create: `frontend/src/views/{approval,repair,user,notification}/**`, 完善 `MainLayout.vue` 菜单角色过滤 + 路由 meta.roles

- [ ] **Step 1: 路由补 meta.roles**

在各 slice 页面路由加 `meta: { roles: ['LAB_ADMIN','SYS_ADMIN'] }`（设备管理/审批/报修处理）或 `['SYS_ADMIN']`（用户/操作日志）。在 `MainLayout.vue` 把侧栏菜单按 `meta.roles ∩ userStore.roles` 过滤。

- [ ] **Step 2: 审批页**

`views/approval/Pending.vue`：待审批列表（LAB_ADMIN 见自辖）+ 通过/拒绝（填理由）/ 批量通过。按钮加 `v-permission="'device:approve'"`。

- [ ] **Step 3: 报修页**

学生：`Submit.vue`(提交) + `Mine.vue`(我的)。管理员：`List.vue`(列表 + take/resolve/reject)。

- [ ] **Step 4: 用户管理（SYS_ADMIN）**

`views/user/Index.vue`：分页表格 + 新增/编辑（含角色绑定）/ 封禁解封。

- [ ] **Step 5: 通知页（轮询版，S3 升级为 WS）**

`views/notification/Index.vue`：`setInterval` 每 30s 轮询 `/notifications/mine`，未读角标在顶栏。标记已读/全部已读。

- [ ] **Step 6: 验证（管理员流）**

LAB_ADMIN 登录 → 待审批通过 → 学生收到（轮询）通知 → 签到 → 归还，设备状态联动正确；报修 take（设备转 MAINTENANCE，新预约被拒）→ resolve（转 IDLE）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views frontend/src/router frontend/src/layouts
git commit -m "feat(fe): 审批/报修/用户管理/通知轮询+菜单角色过滤(S1完成)"
```

---

# Slice S2 — 锁片（Redis 分布式锁）

## Task 11: ReservationLock 封装 + 单测（TDD）

**Files:**
- Create: `src/main/java/com/lab/reservation/service/ReservationLock.java`
- Test: `src/test/java/com/lab/reservation/reservation/ReservationLockTest.java`

- [ ] **Step 1: 写失败测试（mock RedissonClient）**

```java
package com.lab.reservation.reservation;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.service.ReservationLock;
import com.lab.reservation.service.SlotKey;
import org.junit.jupiter.api.*;
import org.redisson.api.*;
import java.time.LocalDate;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ReservationLockTest {
    RedissonClient client; RLock rlock; RLock multi;
    @BeforeEach void setup() {
        client = mock(RedissonClient.class); rlock = mock(RLock.class); multi = mock(RLock.class);
        when(client.getLock(anyString())).thenReturn(rlock);
        when(client.getMultiLock(any(RLock[].class))).thenReturn(multi);
    }

    @Test void acquire_ok() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenReturn(true);
        ReservationLock lock = new ReservationLock(client, 3);
        try (var g = lock.acquire(1L, Set.of(LocalDate.now()))) {
            assertThat(g).isNotNull();
        }
        verify(multi).unlock();   // finally 释放
    }

    @Test void acquire_fail_throws_conflict() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenReturn(false);
        ReservationLock lock = new ReservationLock(client, 3);
        assertThatThrownBy(() -> lock.acquire(1L, Set.of(LocalDate.now())))
            .isInstanceOf(BusinessException.class)
            .extracting("code").isEqualTo(ResultCode.RESERVATION_CONFLICT);
    }

    @Test void redis_down_fail_open() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenThrow(new RuntimeException("redis down"));
        ReservationLock lock = new ReservationLock(client, 3);
        try (var g = lock.acquire(1L, Set.of(LocalDate.now()))) {
            assertThat(g).isNull();   // fail-open：返回 null holder，不抛
        }
    }
}
```

- [ ] **Step 2: 运行测试，确认失败（类不存在）**

Run: `mvn17 -Dtest=ReservationLockTest test`
Expected: 编译失败（ReservationLock 未定义）。

- [ ] **Step 3: 实现 ReservationLock**

```java
package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import java.time.LocalDate;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** 设备预约 Redis 分布式锁：对 (deviceId, date) 加 Redisson MultiLock，看门狗续期，fail-open。 */
@Slf4j
@RequiredArgsConstructor
public class ReservationLock {
    private final RedissonClient client;
    private final long waitSeconds;

    /** 返回 AutoCloseable holder；持锁时 close 释放，fail-open 时返回 null（调用方判空跳过 unlock）。 */
    public Holder acquire(Long deviceId, Set<LocalDate> dates) {
        RLock[] locks = dates.stream()
            .map(date -> client.getLock("lock:dev:" + deviceId + ":" + date))
            .toArray(RLock[]::new);
        RLock multi = client.getMultiLock(locks);
        // ⚠️ tryLock 的 RuntimeException（Redis 不可用）才 fail-open；
        // !locked 的冲突异常须在 try 块【外】抛出，否则会被 catch(RuntimeException) 误吞
        // （BusinessException extends RuntimeException）。实现时 TDD 先写失败用例实测发现此坑并修正。
        boolean locked;
        try {
            locked = multi.tryLock(waitSeconds, -1, TimeUnit.SECONDS); // -1 触发看门狗
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
        } catch (RuntimeException e) {            // Redis 连接异常 → fail-open
            log.warn("Redis unavailable, fail-open to DB unique index", e);
            return null;
        }
        if (!locked) throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
        return new Holder(multi);
    }

    public static class Holder implements AutoCloseable {
        private final RLock multi;
        Holder(RLock multi) { this.multi = multi; }
        @Override public void close() {
            try { if (multi.isHeldByCurrentThread()) multi.unlock(); }
            catch (Exception ignore) {}
        }
    }
}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `mvn17 -Dtest=ReservationLockTest test`
Expected: 3 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/service/ReservationLock.java src/test/java/com/lab/reservation/reservation/ReservationLockTest.java
git commit -m "feat(reservation): ReservationLock(Redisson MultiLock+看门狗+fail-open)TDD"
```

---

## Task 12: 接入 ReservationServiceImpl.create + 注册 bean

**Files:**
- Modify: `src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java`
- Create: `src/main/java/com/lab/reservation/config/LockConfig.java`

- [ ] **Step 1: LockConfig bean**

```java
package com.lab.reservation.config;
import com.lab.reservation.service.ReservationLock;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
@Configuration
public class LockConfig {
    @Bean
    public ReservationLock reservationLock(RedissonClient c,
            @Value("${lab.lock.wait-seconds:3}") long wait) {
        return new ReservationLock(c, wait);
    }
}
```

- [ ] **Step 2: 注入并在 create 加锁**

在 `ReservationServiceImpl` 构造注入 `private final ReservationLock reservationLock;`。在 `create(...)` 中，slot/时长校验之后、`reservationMapper.insert(r)` 之前插入：

```java
Set<LocalDate> dates = slots.stream().map(SlotKey::date).collect(java.util.stream.Collectors.toSet());
try (var ignored = reservationLock.acquire(dto.getDeviceId(), dates)) {
    reservationMapper.insert(r);
    try {
        for (SlotKey s : slots) {
            ReservationItem it = new ReservationItem();
            it.setReservationId(r.getId()); it.setDeviceId(s.deviceId());
            it.setDate(s.date()); it.setSlotIndex(s.slotIndex());
            itemMapper.insert(it);
        }
    } catch (DuplicateKeyException e) {
        throw new BusinessException(ResultCode.RESERVATION_CONFLICT);   // DB 索引兜底
    }
}
// 通知逻辑保持不变
```

> 注意：`create` 仍带 `@Transactional`；锁在事务方法体内 acquire，`try-with-resources` 在方法返回前（commit 前）unlock。`leaseTime=-1` 看门狗会续期，故 unlock 早于 commit 不影响正确性（DB 唯一索引兜底）。

- [ ] **Step 3: 验证现有并发 IT 仍绿（锁已前置）**

Run: `mvn17 -Dtest=ReservationConcurrencyIT test`
Expected: PASS（Phase1 并发语义不变；锁只是多一道前置）。

- [ ] **Step 4: Commit**

```bash
git add src/main/java/com/lab/reservation/config/LockConfig.java src/main/java/com/lab/reservation/service/impl/ReservationServiceImpl.java
git commit -m "feat(reservation): create接入Redisson锁,与DB索引双层防线"
```

---

## Task 13: Redis 锁并发 IT（Testcontainers-redis）

**Files:**
- Test: `src/test/java/com/lab/reservation/reservation/RedisLockConcurrencyIT.java`

- [ ] **Step 1: 写 IT（Testcontainers 起 redis 容器 + 真实 RedissonClient）**

```java
package com.lab.reservation.reservation;

import org.junit.jupiter.api.*;
import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.*;
import com.lab.reservation.service.ReservationLock;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers
class RedisLockConcurrencyIT {
    @Container static GenericContainer<?> redis =
        new GenericContainer<>("redis:7-alpine").withExposedPorts(6379);

    RedissonClient client; ReservationLock lock;
    @BeforeEach void up() {
        Config cfg = new Config();
        cfg.useSingleServer().setAddress("redis://" + redis.getHost() + ":" + redis.getMappedPort(6379));
        client = Redisson.create(cfg);
        lock = new ReservationLock(client, 3);
    }
    @AfterEach void down() { client.shutdown(); }

    @Test void multi_thread_same_device_day_exactly_one_lock() throws Exception {
        int n = 8;
        ExecutorService pool = Executors.newFixedThreadPool(n);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);   // 测试通知持锁者放行
        AtomicInteger acquired = new AtomicInteger();
        Set<LocalDate> day = Set.of(LocalDate.now());
        List<Future<Boolean>> futs = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            futs.add(pool.submit(() -> {
                start.await();
                try (var h = lock.acquire(99L, day)) {
                    if (h == null) return false;          // fail-open（此处不应发生）
                    acquired.incrementAndGet();
                    release.await();                      // 持有者持锁等测试放行再释放
                    return true;
                } catch (com.lab.reservation.exception.BusinessException e) {
                    return false;                         // 3s 内抢不到 → CONFLICT → false
                }
            }));
        }
        start.countDown();
        Thread.sleep(4500);                               // > waitSeconds(3) 让 7 个失败者都返回
        assertThat(acquired.get()).isEqualTo(1);          // 同 device-day 同时只 1 个持锁（确定性）
        release.countDown();                              // 放行持锁者
        pool.shutdown();
        try (var h = lock.acquire(99L, day)) { assertThat(h).isNotNull(); }  // 释放后可再约（无泄漏）
    }

    @Test void different_days_no_blocking() throws Exception {
        try (var a = lock.acquire(1L, Set.of(LocalDate.now()))) {
            long t = System.currentTimeMillis();
            try (var b = lock.acquire(1L, Set.of(LocalDate.now().plusDays(1)))) {
                assertThat(System.currentTimeMillis() - t).isLessThan(2000L); // 不同天不阻塞
            }
        }
    }
}
```

- [ ] **Step 2: 运行 IT**

Run: `mvn17 -Dtest=RedisLockConcurrencyIT test`
Expected: 2 tests PASS（Docker 健康，Testcontainers 自动起 redis 容器）。

- [ ] **Step 3: Commit**

```bash
git add src/test/java/com/lab/reservation/reservation/RedisLockConcurrencyIT.java
git commit -m "test(reservation): Redis锁并发IT(Testcontainers-redis)实证双层防线"
```

---

# Slice S3 — 推送片（WebSocket）

## Task 14: WebSocketConfig + AuthChannelInterceptor + Security 放行 /ws

**Files:**
- Create: `config/WebSocketConfig.java`, `security/ws/AuthChannelInterceptor.java`
- Modify: `security/SecurityConfig.java`（/ws/** permitAll）

- [ ] **Step 1: WebSocketConfig**

```java
package com.lab.reservation.config;

import com.lab.reservation.security.ws.AuthChannelInterceptor;
import org.springframework.context.annotation.*;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.web.socket.config.annotation.*;

@Configuration
@EnableWebSocketMessageBroker
@RequiredArgsConstructor
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {
    private final AuthChannelInterceptor authInterceptor;

    @Override public void registerStompEndpoints(StompEndpointRegistry r) {
        // STOMP 端点路径相对 servlet context（context-path=/api）→ 注册 "/ws"，实际对外 URL=/api/ws
        r.addEndpoint("/ws").setAllowedOriginPatterns("*").withSockJS();
    }
    @Override public void configureMessageBroker(MessageBrokerRegistry r) {
        r.setApplicationDestinationPrefixes("/app");
        r.setUserDestinationPrefix("/user");
        r.enableSimpleBroker("/queue");
    }
    @Override public void configureClientInboundChannel(ChannelRegistration r) {
        r.interceptors(authInterceptor);
    }
}
```

> 端点注册 `/ws`（相对 context-path `/api`），实际对外 URL = `http://localhost:8080/api/ws`。SecurityConfig 放行 `/ws/**`（**不带 /api 前缀**）。前端直连 `http://localhost:8080/api/ws`（SockJS + `setAllowedOriginPatterns("*")` 处理跨域）。

- [ ] **Step 2: AuthChannelInterceptor（CONNECT 头鉴权）**

```java
package com.lab.reservation.security.ws;

import com.lab.reservation.security.JwtUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.*;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.stereotype.Component;
import java.security.Principal;
import java.util.List;

@Component
@RequiredArgsConstructor
public class AuthChannelInterceptor implements ChannelInterceptor {
    private final JwtUtils jwtUtils;

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor acc = StompHeaderAccessor.wrap(message);
        if (StompCommand.CONNECT.equals(acc.getCommand())) {
            List<String> auth = acc.getNativeHeader("Authorization");
            if (auth == null || auth.isEmpty()) throw new MessagingException("Missing Authorization");
            String token = auth.get(0).replace("Bearer ", "").trim();
            Long userId = jwtUtils.parseUserId(token);          // 复用现有 JwtUtils 解析
            if (userId == null) throw new MessagingException("Invalid token");
            final long uid = userId;
            acc.setUser((Principal) () -> String.valueOf(uid)); // convertAndSendToUser 的 user key
        }
        return message;
    }
}
```
（确认 `JwtUtils` 有 `parseUserId(token)`；若无则加一个返回 userId 的方法。）

- [ ] **Step 3: Security 放行 /ws**

`SecurityConfig.authorizeHttpRequests` 中加 `/ws/**` `permitAll()`（**注意：SecurityConfig 的 matcher 路径不带 `/api` 前缀**，context-path 已剥离；鉴权在 CONNECT 帧做）。**不要**加 `/api/ws/**`（永不匹配，是死代码）。

- [ ] **Step 4: 验证启动**

Run: `mvn17 spring-boot:run`
Expected: 无错；SockJS 端点注册日志。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/config/WebSocketConfig.java src/main/java/com/lab/reservation/security/ws/AuthChannelInterceptor.java src/main/java/com/lab/reservation/config/SecurityConfig.java
git commit -m "feat(ws): WebSocketConfig(STOMP+SockJS)+CONNECT头JWT鉴权"
```

---

## Task 15: NotificationService 双写 DB+WS（TDD）

**Files:**
- Modify: `src/main/java/com/lab/reservation/service/impl/NotificationServiceImpl.java`
- Test: `src/test/java/com/lab/reservation/notification/NotificationBroadcastTest.java`

- [ ] **Step 1: 写失败测试（mock SimpMessagingTemplate）**

```java
package com.lab.reservation.notification;

import com.lab.reservation.service.impl.NotificationServiceImpl;
import org.junit.jupiter.api.*;
import org.mockito.*;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import java.util.Map;
import static org.mockito.Mockito.*;

class NotificationBroadcastTest {
    @Mock SimpMessagingTemplate tpl;
    @Test void notify_pushes_to_user_queue() {
        try (MockedConstruction<?> mc = mockConstruction(NotificationServiceImpl.class,
                (impl, ctx) -> {})) {
            // 直接构造被测对象并注入 mock tpl（按实际 NotificationServiceImpl 构造调整）
            NotificationServiceImpl svc = new NotificationServiceImpl(null, tpl);
            svc.notify(7L, "RESERVATION", "预约成功", "设备X", 1L, "RESERVATION");
            verify(tpl).convertAndSendToUser(eq("7"), eq("/queue/notifications"), anyMap());
        }
    }
}
```
> 按实际 `NotificationServiceImpl` 构造与字段调整 mock 注入；核心断言：`convertAndSendToUser(userId, "/queue/notifications", payload)` 被调用。

- [ ] **Step 2: 运行确认失败**

Run: `mvn17 -Dtest=NotificationBroadcastTest test` → FAIL（未推送）。

- [ ] **Step 3: 实现：注入 SimpMessagingTemplate，notify 末尾推送**

在 `NotificationServiceImpl` 注入 `SimpMessagingTemplate messagingTemplate`，`notify(...)` 在 `notificationMapper.insert(n)` 之后：

```java
messagingTemplate.convertAndSendToUser(
    String.valueOf(userId), "/queue/notifications",
    Map.of("id", n.getId(), "type", type, "title", title,
           "content", content, "relatedId", relatedId,
           "relatedType", relatedType, "createdAt", n.getCreatedAt()));
```

- [ ] **Step 4: 运行确认通过**

Run: `mvn17 -Dtest=NotificationBroadcastTest test` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/service/impl/NotificationServiceImpl.java src/test/java/com/lab/reservation/notification/NotificationBroadcastTest.java
git commit -m "feat(notification): notify双写DB持久化+WS实时推送"
```

---

## Task 16: 前端 useWebSocket + notificationStore + 实时 toast

**Files:**
- Create: `frontend/src/composables/useWebSocket.ts`, `frontend/src/stores/notification.ts`
- Modify: `frontend/src/layouts/MainLayout.vue`（挂 WS）

- [ ] **Step 1: useWebSocket.ts（@stomp/stompjs + SockJS，CONNECT 带 Authorization）**

```ts
import { Client } from '@stomp/stompjs'
import SockJS from 'sockjs-client'
import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'

let client: Client | null = null
export function connectWs() {
  const u = useUserStore()
  if (!u.accessToken || client) return
  client = new Client({
    webSocketFactory: () => new SockJS('http://localhost:8080/api/ws'),
    connectHeaders: { Authorization: `Bearer ${u.accessToken}` },
    onConnect: () => {
      client!.subscribe('/user/queue/notifications', (msg) => {
        const body = JSON.parse(msg.body)
        useNotificationStore().onMessage(body)
      })
    },
  })
  client.activate()
}
export function disconnectWs() { client?.deactivate(); client = null }
```

- [ ] **Step 2: stores/notification.ts（角标 + toast）**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import * as notifApi from '@/api/notification'

export const useNotificationStore = defineStore('notification', () => {
  const unread = ref(0)
  // 无独立 unread-count 端点；用 /notifications/mine?onlyUnread 的分页 total 得未读数
  async function loadUnread() {
    const res: any = await notifApi.mine({ onlyUnread: true, page: 1, size: 1 })
    unread.value = res?.total ?? 0
  }
  function onMessage(body: any) {
    unread.value++
    ElNotification({ title: body.title, message: body.content, type: 'info' })
  }
  return { unread, loadUnread, onMessage }
})
```

- [ ] **Step 3: MainLayout 挂接 + 登录后建连**

`MainLayout.vue` `onMounted`: `connectWs(); notifStore.loadUnread()`；`onUnmounted`/登出 `disconnectWs()`。顶栏显示未读角标。

- [ ] **Step 4: 验证（两浏览器实时演示）**

浏览器 A 学生登录、浏览器 B LAB_ADMIN 登录。B 审批通过 A 的预约 → A 浏览器**实时**弹 toast + 角标 +1。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useWebSocket.ts frontend/src/stores/notification.ts frontend/src/layouts/MainLayout.vue
git commit -m "feat(fe): STOMP实时推送(CONNECT头鉴权)+未读角标+toast"
```

---

# Slice S4 — 驾驶舱片（ECharts）

## Task 17: 后端富指标 + 角色 overview/me（TDD）

**Files:**
- Modify: `mapper/ReservationItemMapper.java`/`ReservationMapper.java`（聚合查询）, `service/DashboardService.java`(+impl), `controller/DashboardController.java`
- Create: `vo/dashboard/DashboardOverviewVO.java` 等
- Test: `src/test/java/com/lab/reservation/dashboard/DashboardServiceTest.java`

- [ ] **Step 1: 写失败测试（mock mapper）**

```java
// DashboardServiceTest 至少覆盖：
@Test void overview_assembles_all_widgets() {
    // mock 各 mapper 返回固定聚合 → 断言 OverviewVO 含 deviceStatus/trend30d/utilization/heatmap/
    // categoryDist/repairStats/cards 字段且数值来自 mock（如 deviceStatus.IDLE=10）
}
@Test void lab_admin_scope_passes_managed_lab_ids() {
    // LAB_ADMIN：managedLabIds 返回非空 list → verify 各聚合 mapper 调用参数含该 labIds
}
@Test void sys_admin_scope_no_lab_filter() {
    // SYS_ADMIN：managedLabIds 返回 null → verify 聚合 mapper 调用 labIds 参数为 null（不过滤）
}
@Test void second_call_hits_redis_cache() {
    // 同用户连续两次 getOverview → 重聚合 mapper 只被调用一次（第二次命中缓存）
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn17 -Dtest=DashboardServiceTest test` → FAIL。

- [ ] **Step 3: 实现 mapper 聚合 + Service 装配 + 角色分支 + Redis 缓存**

- `ReservationItemMapper` 加：`selectUtilization(List<Long> labIds, int days)`、`selectPeakHeatmap(...)`、`selectPopularity(...)`（MyBatis-Plus `@Select` 或 XML）。deviceStatus/categoryDist/repairStats 走对应 mapper 的聚合。
- `DashboardService.getOverview(SecurityUserDetails)`：按 `LabScopeHelper.managedLabIds` 三态决定 labIds 过滤；组装 `DashboardOverviewVO`；重查询走 `StringRedisTemplate` 缓存（key `dash:overview:{role}:{userId}:{md5(scope)}`，TTL 配置）。
- `DashboardService.getMe(SecurityUserDetails)`：STUDENT 个人视角。
- `DashboardController` 加 `GET /dashboard/overview`、`GET /dashboard/me`，`@PreAuthorize` 按角色。

- [ ] **Step 4: 运行确认通过**

Run: `mvn17 -Dtest=DashboardServiceTest test` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/{mapper,service,controller,vo/dashboard} src/test/java/com/lab/reservation/dashboard/DashboardServiceTest.java
git commit -m "feat(dashboard): 富指标聚合(利用率/热力/类目)+角色overview/me+Redis缓存"
```

---

## Task 18: 前端 ECharts 驾驶舱（角色三视角）

**Files:**
- Create: `frontend/src/views/dashboard/{Admin,LabAdmin,Student}.vue`, `components/charts/{PieChart,LineChart,BarChart,HeatmapChart}.vue`, `composables/useEcharts.ts`
- Modify: `views/dashboard/Index.vue`（按角色分发）

- [ ] **Step 1: useEcharts + 图表组件（vue-echarts 懒加载，Cal.com 配色）**

`components/charts/BarChart.vue` 等用 `vue-echarts` `<v-chart>`，颜色取 Cal.com DESIGN.md 调色板。`useEcharts.ts` 全局注册所需 echarts 组件。

- [ ] **Step 2: Index.vue 按角色分发**

```ts
const u = useUserStore()
const comp = computed(() =>
  u.hasRole('STUDENT') ? Student : u.hasRole('LAB_ADMIN') ? LabAdmin : Admin)
```

- [ ] **Step 3: Admin/LabAdmin.vue** 调 `/dashboard/overview` 渲染 状态饼/趋势折线/利用率柱/热力/类目/报修柱 + 数字卡。
**Student.vue** 调 `/dashboard/me` 渲染 我的预约(按状态)饼/我的趋势/我的常用类目。

- [ ] **Step 4: 验证（三角色分别看驾驶舱）**

三角色登录各看对应驾驶舱，图表渲染正确、数据按 scope（LAB_ADMIN 只见自辖）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/dashboard frontend/src/components/charts frontend/src/composables/useEcharts.ts
git commit -m "feat(fe): ECharts驾驶舱(角色三视角,vue-echarts,Cal.com配色)"
```

---

# Slice S5 — 推荐片

## Task 19: 后端 RecommendationService（混合启发式，TDD）

**Files:**
- Create: `service/RecommendationService.java`(+impl), `controller/RecommendationController.java`, `dto/recommendation/`, `vo/recommendation/RecommendationItemVO.java`
- Modify: `mapper/ReservationMapper.java`（用户历史聚合 + 全站热度）
- Test: `src/test/java/com/lab/reservation/recommendation/RecommendationServiceTest.java`

- [ ] **Step 1: 写失败测试（mock mapper）**

```java
// RecommendationServiceTest 至少覆盖：
@Test void history_user_top_is_affinity_category_with_reason() {
    // 用户历史全在类目"显微镜" → top1 为该类目设备 + reason 含"常约"
}
@Test void cold_start_user_degrades_to_popularity() {
    // 无历史 → 排序按 γ 热度 + reason == "热门设备"
}
@Test void maintenance_device_excluded_and_active_reservation_penalized() {
    // MAINTENANCE 设备不在结果；用户有活跃预约的设备得分被 −ε 降权
}
@Test void second_call_hits_cache() {
    // 同用户连调两次 → 历史/热度 mapper 只查一次（第二次命中 rec:u:{userId} 缓存）
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn17 -Dtest=RecommendationServiceTest test` → FAIL。

- [ ] **Step 3: 实现**

- `RecommendationService.recommend(Long userId, int limit)`：
  - 取用户历史：`categoryAffinity`(类目→占比)、`labAffinity`、`usedDeviceIds`、`prefTags`（从历史设备 tags 聚合）。
  - 候选设备：所有 IDLE（排除 MAINTENANCE）。
  - 逐设备算分（按 §9.1 公式，权重从 `lab.recommend.weights` 注入）；已用设备 −ε。
  - reason：最高权重项 → 文案（α→"因你常约【类目】"、γ→"近30天热门设备"、δ→"标签匹配"）；并列优先 α。
  - 冷启动（无历史）：α=β=0，仅 γ 排序，reason="热门设备"。
  - 取 top-limit，缓存 `rec:u:{userId}`（TTL 配置），返回 `List<RecommendationItemVO>`。
- `RecommendationController`：`GET /recommendations?limit=10`，登录即可（STUDENT）。

- [ ] **Step 4: 运行确认通过**

Run: `mvn17 -Dtest=RecommendationServiceTest test` → PASS。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/{service,mapper,controller,dto/recommendation,vo/recommendation} src/test/java/com/lab/reservation/recommendation/RecommendationServiceTest.java
git commit -m "feat(recommend): 混合启发式推荐(打分+理由+冷启动+Redis缓存)TDD"
```

---

## Task 20: 前端"为你推荐"区

**Files:**
- Create: `frontend/src/views/recommendation/Index.vue`（或嵌入设备列表页顶部）
- Modify: 路由 + 菜单（STUDENT 可见）

- [ ] **Step 1: 推荐区组件**

调 `/recommendations?limit=10`，卡片网格展示 设备名 + 推荐理由（`el-tag` 高亮）+ 分数条。按 Cal.com DESIGN.md 卡片样式。

- [ ] **Step 2: 验证**

学生登录（先用现有有预约历史的学生账号，或先造几条预约）→ 见个性化推荐 + 理由；新注册学生 → 见热度推荐 + "热门设备"。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/recommendation frontend/src/router frontend/src/layouts
git commit -m "feat(fe): 为你推荐(个性化+理由,STUDENT)"
```

---

# 收尾

## Task 21: 全量回归 + DoD 核验

**Files:** 全项目

- [ ] **Step 1: 后端全量测试（Phase1 零回归 + 新增）**

Run: `mvn17 test`
Expected: Phase1 的 39 + S2/S3/S4/S5 新增全绿，0 failures。

- [ ] **Step 2: 前端构建 + 单测**

Run（frontend/）: `pnpm build && pnpm test`
Expected: build 成功产出 dist/；vitest 关键纯逻辑单测绿。

- [ ] **Step 3: compose + 两端启动**

Run: `docker compose up -d` && `mvn17 spring-boot:run` && `pnpm dev`
Expected: 全栈起，登录通。

- [ ] **Step 4: DoD 逐项冒烟（三角色 × 四亮点）**

- S1 三角色全流程（浏览→预约→审批→签到→归还→通知→报修）✓
- S2 脚本并发抢同一槽 → 恰一个成功 ✓（可用 Knife4j 或并发 IT 演示）
- S3 两浏览器实时推送 ✓
- S4 三角色 ECharts 图表正确 ✓
- S5 学生个性化推荐 + 理由 ✓
- 前端视觉对照 Cal.com DESIGN.md 的 Do's & Don'ts 自检（无 AI 味）✓

- [ ] **Step 5: Commit（如有收尾小改）**

```bash
git add -A
git commit -m "test(all): 全量回归绿+DoD核验通过"
```

---

## 完成后

进入 `superpowers:finishing-a-development-branch`：验证测试 → 给出 4 选项（合并 main / 推 PR / 保留分支 / 丢弃）→ 执行 → 清理。
