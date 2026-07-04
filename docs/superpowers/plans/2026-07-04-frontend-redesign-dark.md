# 前端视觉重设计(科技深色)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Vue3 + Element Plus 前端从 Cal.com 营销浅色风全面重做为科技深色(Linear/Vercel 风,青电光蓝强调,丰富但克制的动效),覆盖全量 18 页,业务逻辑零改动。

**Architecture:** 方案 A — Token 纵切。先建深色设计系统层(全量 CSS token + Element Plus 暗色覆盖 + ECharts 深色主题 + 字体),再建通用组件库(14 件)+ 动效基建,最后逐页套用。改动全在 `frontend/` 样式层,后端零影响。7 个 slice(R0 基建 → R1 组件库 → R2 登录 → R3 驾驶舱 → R4 设备 → R5 预约/审批/报修/推荐 → R6 收尾)。

**Tech Stack:** Vue 3.5 / Element Plus 2.14 / ECharts 6 / Pinia / vue-router 5 / Sass / `@vueuse/core` + `@vueuse/motion` / `@fontsource/*`(Inter + Space Grotesk + JetBrains Mono)。

**Spec:** `docs/superpowers/specs/2026-07-04-frontend-redesign-design.md`(token 表、组件职责、逐页处理、动效铁律的权威来源,本计划引用其值不再重复)。

---

## TDD 适配说明(重要)

本计划是**视觉重做**,纯 CSS/模板的"测试"无法用断言表达。因此:
- **有运行时逻辑的任务**(composable:`useCountUp`/`useStagger`;指令:`v-reduced-motion`;交互组件:SegmentedControl/Timeline 的状态切换)→ **写 vitest**(TDD:先红后绿)。
- **纯样式/模板任务**(token 文件、MainLayout 重构、各业务页换肤)→ **验证 = `pnpm build` 干净 + 浏览器冒烟**(由 R6 统一收尾冒烟;每 task 至少 `pnpm build` 过)。
- 所有任务都以 **commit** 收尾(频繁提交)。

## 全局执行约束(给所有子代理)

1. **只动 `frontend/`**。不碰 `docker-compose*`、不启停 `spring-boot:run`、不杀 java 进程(后端由主控会话常驻,撞了会断 DB 连接退出)。
2. **前端验证命令**:`cd frontend && pnpm test`(vitest)、`cd frontend && pnpm build`(vue-tsc + vite build)。dev server(`pnpm dev`)子代理可自行启停。
3. **包管理器 = pnpm**(项目已用 corepack pnpm9)。装新依赖:`cd frontend && pnpm add <pkg>`。
4. **token 值以 spec §3.1 为准**,本计划引用变量名,不重复列 hex(避免漂移)。
5. **每个 slice 收尾过 `frontend-design` 复审**(防 AI 味/动效铁律 §6.1)。impeccable 装上后可替换。
6. **commit message 中文,带 `Co-Authored-By: Claude <noreply@anthropic.com>`**。

## 文件结构(创建/修改清单)

**新建**
- `frontend/src/styles/theme.dark.scss` — 全量深色 token(取代 `theme.scss` 的角色,`main.ts` 改引此文件)
- `frontend/src/styles/_motion.scss` — 动效 token(easing/duration)+ 通用 keyframes(aurora/shimmer/page)
- `frontend/src/composables/useCountUp.ts` — 数字滚动(rAF)
- `frontend/src/composables/useStagger.ts` — 错峰入场(IntersectionObserver,基于 `@vueuse/core`)
- `frontend/src/directives/reducedMotion.ts` — `v-reduced-motion`(命中 `prefers-reduced-motion` 时禁用动效)
- `frontend/src/components/ui/` — 14 件:`PageHeader.vue`/`Panel.vue`/`GlowCard.vue`/`StatCard.vue`/`StatusDot.vue`/`GradientButton.vue`/`GhostButton.vue`/`TextButton.vue`/`Skeleton.vue`/`EmptyState.vue`/`SegmentedControl.vue`/`Timeline.vue`/`Tag.vue`/`Badge.vue`
- `frontend/src/styles/echarts-dark-theme.ts` — ECharts 自定义深色主题 JSON
- `frontend/DESIGN.dark.md` — 新设计源真相(spec 精简版)
- `docs/thesis/screenshots/` — 三角色截图(R6)

**修改**
- `frontend/src/main.ts` — 引 EP 暗色 css-vars + `theme.dark.scss` + fontsource + `html.dark` + 注册 echarts 深色主题 + 注册 `v-reduced-motion`
- `frontend/src/composables/useEcharts.ts` — 注册深色主题,默认 theme='dark'
- `frontend/src/layouts/MainLayout.vue` — §4 深色重构
- `frontend/src/App.vue` — 加全局氛围光层 + `<Transition>` 包 `<router-view>`(若 App.vue 是纯 `<router-view/>`,氛围光放 MainLayout/Login 各自)
- `frontend/src/router/index.ts` — 加页面 transition meta(可选)
- `frontend/src/views/**/*.vue` — 18 页逐页套新组件 + 深色 scoped 样式
- `frontend/src/components/charts/{Bar,Line,Pie,Heatmap}Widget.vue` + `BaseChart.vue` — 默认用深色主题(改 useEcharts 默认值即可,组件结构不动)
- `frontend/src/components/charts/palette.ts` — 重调深色色板
- `frontend/index.html` — 可选:加 `<meta name="color-scheme" content="dark">`(防表单控件默认浅色)
- `frontend/package.json` — 加 `@vueuse/core` `@vueuse/motion` `@fontsource/inter` `@fontsource/space-grotesk` `@fontsource/jetbrains-mono`

**删除**
- `frontend/src/style.css`(死文件,Vite 脚手架残留)
- `frontend/src/components/HelloWorld.vue`(死文件)

---

# Slice R0 — 基建(深色 token + 字体 + EP 暗色 + ECharts 深色 + 壳重构 + 动效基建 + 清理)

**目标:** 全站已变深色骨架(含图表),vitest 零回归,为后续组件/页面铺好地基。

### Task R0.1: 装依赖 + 删死文件

**Files:**
- Modify: `frontend/package.json`
- Delete: `frontend/src/style.css`, `frontend/src/components/HelloWorld.vue`

- [ ] **Step 1: 装依赖**

```bash
cd frontend
pnpm add @vueuse/core @vueuse/motion
pnpm add @fontsource/inter @fontsource/space-grotesk @fontsource/jetbrains-mono
```
Expected: package.json 多 5 个 dep,pnpm-lock 更新。

- [ ] **Step 2: 删死文件**

```bash
rm frontend/src/style.css
rm frontend/src/components/HelloWorld.vue
```
确认 `style.css` 未被任何文件 import(`main.ts` 只引 `vue-echarts/style.css` 与 `theme.scss`,不误删)。

- [ ] **Step 3: build 验证未回归**

```bash
cd frontend && pnpm build
```
Expected: build 干净(style.css/HelloWorld 本就未引用)。

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git rm frontend/src/style.css frontend/src/components/HelloWorld.vue
git commit -m "chore(fe): 装动效/字体依赖+删Vite脚手架死文件(style.css/HelloWorld)"
```

### Task R0.2: 写深色 token 文件 `theme.dark.scss`

**Files:**
- Create: `frontend/src/styles/theme.dark.scss`
- Reference: spec §3.1(token 值权威表)

- [ ] **Step 1: 写 `theme.dark.scss`**

按 spec §3.1 完整列 token(`--bg-base/surface/elevated/sunken`、`--border-subtle/default/strong`、`--text-primary/secondary/tertiary/on-accent`、`--accent/-bright/-deep`、`--grad-accent`、`--glow-accent`、`--status-*`)+ 字体变量(`--font-sans: Inter`、`--font-display: "Space Grotesk"`、`--font-mono: "JetBrains Mono"`)+ Element Plus 暗色变量全量映射(`--el-color-primary: var(--accent)`、`--el-bg-color/page/overlay`、`--el-text-color-*`、`--el-border-color*`、`--el-fill-color*`、`--el-box-shadow*`)+ `body`/`#app` 基础(深色底、Inter 字体、font-smoothing)+ `.lab-card` 升级为深色卡(保留类名兼容旧视图)。

文件顶部先 `@use` 引 element-plus 暗色底(由 main.ts import 顺序保证),再 `:root` 覆盖。

- [ ] **Step 2: 切换 main.ts 引用**

`frontend/src/main.ts`:把 `import './styles/theme.scss'` 改为 `import './styles/theme.dark.scss'`;新增 `import 'element-plus/theme-chalk/dark/css-vars.css'`(在 element-plus/dist/index.css 之后、theme.dark.scss 之前);挂载前 `document.documentElement.classList.add('dark')`;引 fontsource(`@fontsource/inter/400.css` `500.css` `600.css`、`@fontsource/space-grotesk/600.css`、`@fontsource/jetbrains-mono/400.css`)。

- [ ] **Step 3: index.html 加 color-scheme**

`frontend/index.html` `<head>` 加 `<meta name="color-scheme" content="dark">`(防原生表单控件浅色)。

- [ ] **Step 4: build + 浏览器瞄一眼**

```bash
cd frontend && pnpm build && pnpm dev
```
浏览器开 dev server,任意页应已整体深色(EP 组件变深)。**纯视觉,无 vitest。**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/theme.dark.scss frontend/src/main.ts frontend/index.html
git commit -m "feat(fe): R0深色token全量+EP暗色css-vars+fontsource字体"
```

### Task R0.3: ECharts 深色主题 + palette 重调

**Files:**
- Create: `frontend/src/styles/echarts-dark-theme.ts`
- Modify: `frontend/src/composables/useEcharts.ts`, `frontend/src/components/charts/palette.ts`

- [ ] **Step 1: 写深色主题 JSON**

`echarts-dark-theme.ts` 导出 ECharts theme object:背景透明、文字色 `--text-secondary`、坐标轴线/分割线 `--border-subtle`、tooltip 深色 `--bg-elevated`、数据色板用青→蓝渐变系(`#22d3ee #3b82f6 #34d399 #fbbf24 #f87171 #a78bfa`)。

- [ ] **Step 2: useEcharts 注册并设默认**

`useEcharts.ts`:在 `setupEcharts()` 里 `echarts.registerTheme('lab-dark', theme)`;导出的 BaseChart composable 默认 `theme='lab-dark'`。

- [ ] **Step 3: palette.ts 重调**

`charts/palette.ts`:把浅色色板换成深色版(青/蓝/状态语义),导出名不变(兼容 Widget 引用)。

- [ ] **Step 4: build + 浏览器瞄驾驶舱图表**

```bash
cd frontend && pnpm build
```
浏览器看 Dashboard 图表变深色。**纯视觉。**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/echarts-dark-theme.ts frontend/src/composables/useEcharts.ts frontend/src/components/charts/palette.ts
git commit -m "feat(fe): R0 ECharts自定义深色主题+palette重调"
```

### Task R0.4: 动效基建(token + composable + 指令,TDD)

**Files:**
- Create: `frontend/src/styles/_motion.scss`, `frontend/src/composables/useCountUp.ts`, `frontend/src/composables/useStagger.ts`, `frontend/src/directives/reducedMotion.ts`
- Test: `frontend/src/composables/__tests__\useCountUp.test.ts`, `...\useStagger.test.ts`, `frontend/src/directives/__tests__\reducedMotion.test.ts`

- [ ] **Step 1: 写 `useCountUp` 失败测试**

```ts
// useCountUp.test.ts
import { useCountUp } from '../useCountUp'
import { ref } from 'vue'

test('从0插值到目标值', async () => {
  const target = ref(100)
  const display = useCountUp(target, { duration: 50, active: ref(true) })
  // 等 raf 链跑完
  await new Promise(r => setTimeout(r, 200))
  expect(display.value).toBeCloseTo(100, 0)
})

test('prefers-reduced-motion 命中时直跳目标', async () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  const target = ref(42)
  const display = useCountUp(target, { duration: 50, active: ref(true) })
  await new Promise(r => setTimeout(r, 30))
  expect(display.value).toBe(42)
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && pnpm test useCountUp
```
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `useCountUp.ts`**

`useCountUp(target: Ref<number>, { duration=1000, active })`:watch target+active,active 且非 reduced-motion 时用 requestAnimationFrame + easeOutExpo 从当前值插值到 target.value;reduced-motion 或 active=false 时直接 = target.value。返回 `display: Ref<number>`。reduced-motion 用 `window.matchMedia('(prefers-reduced-motion: reduce)')`。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && pnpm test useCountUp
```
Expected: PASS。

- [ ] **Step 5: 写 + 实现 `useStagger.ts`(TDD 同上)**

`useStagger(containerRef, { delay=60 })`:用 `@vueuse/core` `useIntersectionObserver` 监听容器内 `[data-stagger]` 子元素,进入视口时按 index×delay 设 `--stagger-delay` 并加 `.stagger-in` 类。测试:mock IntersectionObserver,断言回调按 index 设 delay。先红后绿。

- [ ] **Step 6: 写 + 实现 `reducedMotion.ts` 指令(TDD)**

`v-reduced-motion`:mounted 时若 `matchMedia('(prefers-reduced-motion: reduce)').matches`,给元素加 `style` 把 `animation/transition: none`。测试:stub matchMedia matches=true,断言元素 style.transition==='none'。先红后绿。

- [ ] **Step 7: 写 `_motion.scss`**

token:`--ease-out-expo: cubic-bezier(.16,1,.3,1)`、`--d-fast/.15s`、`--d-med/.28s`、`--d-slow/.5s`。keyframes:`@keyframes aurora`(径向辉光位移动画,12s)、`@keyframes shimmer`(骨架扫光)、`@keyframes page-enter`(opacity 0→1 + translateY 8px→0)。通用类:`.page-enter-active/.page-enter-from`(router transition)、`.shimmer`、`.aurora-bg`。

- [ ] **Step 8: main.ts 注册指令**

`app.directive('reduced-motion', vReducedMotion)`;import `_motion.scss`。

- [ ] **Step 9: 全量 vitest**

```bash
cd frontend && pnpm test
```
Expected: 全绿(含新增 3 测试)。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/composables frontend/src/directives frontend/src/styles/_motion.scss frontend/src/main.ts
git commit -m "feat(fe): R0动效基建(useCountUp/useStagger/v-reduced-motion+motion token)"
```

### Task R0.5: MainLayout 深色重构(§4)

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1: 重写 MainLayout template + scoped style**

按 spec §4:侧栏 `--bg-sunken` + 右 hairline + 品牌字(Space Grotesk)+ 青色脉冲点 logo;菜单 active 左侧 2px 青指示条 + `--bg-elevated` + 青图标(用 EP `el-menu` 的 `--el-menu-*` 暗色变量覆盖 + 自定义 `.is-active` 样式);顶栏毛玻璃 `backdrop-filter: blur(12px)` sticky + hairline 底 + 通知铃未读青点 + 头像青在线环;主区 `--bg-base` + 内容容器;全局氛围光 fixed div(`.aurora-bg` 极弱青辉,左上角)。

- [ ] **Step 2: build + 浏览器瞄**

```bash
cd frontend && pnpm build
```
浏览器看后台壳变深色科技风。**纯视觉。**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/layouts/MainLayout.vue
git commit -m "feat(fe): R0 MainLayout深色重构(毛玻璃顶栏/脉冲logo/青指示条/氛围光)"
```

### Task R0.6: 全局氛围光 + page transition

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: App.vue 加氛围光层 + router transition**

```vue
<template>
  <div class="app-shell">
    <div class="aurora-bg" aria-hidden="true" />
    <router-view v-slot="{ Component }">
      <transition name="page">
        <component :is="Component" />
      </router-view>
    </router-view>
  </div>
</template>
```
scoped style:`.app-shell{position:relative;min-height:100vh}`;`.aurora-bg` fixed 全屏 pointer-events:none z-index:0,主内容 `position:relative;z-index:1`。`.page-enter-active/.page-leave-active{transition:opacity .28s var(--ease-out-expo),transform .28s var(--ease-out-expo)}`;`.page-enter-from{opacity:0;transform:translateY(8px)}`。

- [ ] **Step 2: build + 浏览器看页面切换淡入**

```bash
cd frontend && pnpm build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat(fe): R0 App全局氛围光+router页面transition"
```

### Task R0.7: Slice R0 收尾(回归 + 复审)

- [ ] **Step 1: 全量 vitest + build**

```bash
cd frontend && pnpm test && pnpm build
```
Expected: vitest 全绿(零回归)、build 干净。

- [ ] **Step 2: 过 frontend-design 复审 R0**

dispatch `frontend-design` skill 子代理审 MainLayout + theme.dark.scss + 动效铁律 §6.1。修关键 issue。

- [ ] **Step 3: 写 `frontend/DESIGN.dark.md`**(新设计源真相:token 表精简 + Do/Don't + 动效铁律,从 spec §3/§6 提炼)。

- [ ] **Step 4: Commit**

```bash
git add frontend/DESIGN.dark.md
git commit -m "docs(fe): DESIGN.dark.md 新深色设计源真相"
```

---

# Slice R1 — 通用组件库(14 件)+ StatCard 迁移

**目标:** 设计系统原语层就绪,可独立渲染,vitest 绿。

### Task R1.1: 静态组件批(PageHeader/Panel/GlowCard/GradientButton/GhostButton/TextButton/Skeleton/EmptyState/Tag/Badge)

**Files:**
- Create: `frontend/src/components/ui/{PageHeader,Panel,GlowCard,GradientButton,GhostButton,TextButton,Skeleton,EmptyState,Tag,Badge}.vue`

- [ ] **Step 1: 逐组件实现**(均纯展示 + scoped scss,走 token)

- `PageHeader.vue`:props `title/subtitle`,slot `#actions`/`#breadcrumb`。Space Grotesk 标题,底部 hairline + 下边距。
- `Panel.vue`:slot default,`--bg-surface` + hairline + hover `-2px` 抬升 + 过渡。props `accent?:boolean`(顶部青条)。
- `GlowCard.vue`:`<Panel>` + hover 辉光增强(`box-shadow: var(--glow-accent)` on hover)。
- `GradientButton.vue`:包 `el-button`,背景 `var(--grad-accent)`,文字 `--text-on-accent`,hover 增亮 + 辉光,press 收缩 `transform: scale(.98)`。透传 props/slots(`v-bind="$attrs"`)。
- `GhostButton.vue`:`el-button` hairline 边,hover 青字 + 青边。
- `TextButton.vue`:`el-button text`,hover 青。
- `Skeleton.vue`:props `variant: 'text'|'rect'|'circle'`、`width/height`。`.shimmer` 动画背景。
- `EmptyState.vue`:props `icon/description`,slot `#action`。居中,弱辉光。
- `Tag.vue`:包 `el-tag`,variant 映射到深色 semi-fill(用 token 状态色 + rgba 背景)。
- `Badge.vue`:包 `el-badge`,深色调。

- [ ] **Step 2: build 验证**

```bash
cd frontend && pnpm build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui
git commit -m "feat(fe): R1 静态UI组件批(PageHeader/Panel/GlowCard/3按钮/Skeleton/EmptyState/Tag/Badge)"
```

### Task R1.2: StatusDot(状态语义,TDD)

**Files:**
- Create: `frontend/src/components/ui/StatusDot.vue`
- Test: `frontend/src/components/ui/__tests__\StatusDot.test.ts`

- [ ] **Step 1: 写失败测试**(mount,传 `status="IN_USE"`,断言渲染含 `status-dot--in-use` 类 + 文案 "使用中")

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 实现 StatusDot.vue**

props `status: 'IDLE'|'IN_USE'|'MAINTENANCE'|'BROKEN'`(映射表 IDLE 灰/IN_USE 青脉冲/MAINTENANCE 琥珀/BROKEN 红)+ `label?:boolean`(显隐文字)。脉冲用 CSS keyframes `@keyframes pulse`(box-shadow 扩散)。颜色 token 映射。

- [ ] **Step 4: 跑确认通过**

- [ ] **Step 5: Commit** `feat(fe): R1 StatusDot(状态脉冲点,TDD)`

### Task R1.3: StatCard + count-up(TDD)+ charts/StatCard 迁移

**Files:**
- Create: `frontend/src/components/ui/StatCard.vue`
- Delete: `frontend/src/components/charts/StatCard.vue`(迁移后)
- Modify: 引用旧 StatCard 的视图(R3 Dashboard 处理;此处先建新件 + 标记旧件将在 R3 替换)
- Test: `frontend/src/components/ui/__tests__\StatCard.test.ts`

- [ ] **Step 1: 写失败测试**(mount,props `value=1280 label="设备"`,断言显示标签 + 数字节点存在;count-up 逻辑由 useCountUp 单测覆盖,组件测只验渲染 + label)

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 实现 StatCard.vue**

props:`value:number`、`label:string`、`trend?:{delta:number;dir:'up'|'down'}`、`icon?:string`、`unit?:string`。内部 `const display = useCountUp(toRef(props,'value'), {active: inView})`,`inView` 用 `useIntersectionObserver`;数字 JetBrains Mono + Space Grotesk?数字用 mono;趋势 delta 绿/红;icon chip 青色 tint。

- [ ] **Step 4: 跑确认通过**

- [ ] **Step 5: Commit** `feat(fe): R1 StatCard(count-up+趋势,TDD)`

> 旧 `charts/StatCard.vue` 的删除 + 视图改引放 R3(Dashboard)统一做,避免本 slice 留断引用。

### Task R1.4: SegmentedControl(滑块动效,TDD)

**Files:**
- Create: `frontend/src/components/ui/SegmentedControl.vue`
- Test: `.../__tests__\SegmentedControl.test.ts`

- [ ] **Step 1: 写失败测试**(v-model 双向:传 modelValue='a' options=[{value:'a'},{value:'b'}],点击 b → emit update:modelValue 'b';active 滑块 transform 跟随)

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 实现 SegmentedControl.vue**

props `modelValue/options`(`v-model`),底槽 `--bg-sunken` pill,选中项青色 pill 滑块(绝对定位 `transform: translateX(...)`,过渡 `var(--d-med) var(--ease-out-expo)`)。emit `update:modelValue`。

- [ ] **Step 4: 跑确认通过**

- [ ] **Step 5: Commit** `feat(fe): R1 SegmentedControl(滑块动效,TDD)`

### Task R1.5: Timeline(TDD)

**Files:**
- Create: `frontend/src/components/ui/Timeline.vue`
- Test: `.../__tests__\Timeline.test.ts`

- [ ] **Step 1: 写失败测试**(props items=[{title,time,status:'done'}, {title,status:'current'}],断言渲染两项 + current 项含青色节点类)

- [ ] **Step 2: 跑确认失败**

- [ ] **Step 3: 实现 Timeline.vue**

props `items:{title;desc?;time?;status:'done'|'current'|'todo'}[]`。垂直轴 + 节点点(done 灰实心/current 青脉冲/todo 空心 hairline)+ 连接线。每项 fade-in。

- [ ] **Step 4: 跑确认通过**

- [ ] **Step 5: Commit** `feat(fe): R1 Timeline(垂直时间轴,TDD)`

### Task R1.6: R1 收尾

- [ ] **Step 1: 全量 vitest + build**(`cd frontend && pnpm test && pnpm build`)
- [ ] **Step 2: 过 frontend-design 复审组件库**(token 一致性、动效铁律)
- [ ] **Step 3: (可选)建临时 demo 路由 `/ui-preview`** 渲染全部 14 组件供目检,R6 删。Commit `chore(fe): R1 UI预览页(临时,目检用)`。

---

# Slice R2 — 登录页 hero

### Task R2.1: Login 分屏 hero + 玻璃卡

**Files:**
- Modify: `frontend/src/views/login/Login.vue`

- [ ] **Step 1: 重写 Login template + scoped style**

分屏:左 `.login-hero`(极光 `aurora-bg` 流动 + Space Grotesk 产品名 + tagline + 2-3 漂浮设备卡碎片 `<GlowCard>` 缩略),右 `.login-form-wrap`(毛玻璃 `<Panel>` 登录卡,`backdrop-filter: blur(20px)` + 半透明 `--bg-surface/80`)。入场:`.login-hero`/`.login-card` 用 `v-motion`(`@vueuse/motion`)fade+rise stagger。保留登录逻辑零改。移除硬编码 username/password 预填?保留(admin/admin123 便于答辩 demo,但 R6 可清)。

- [ ] **Step 2: build + 浏览器实测登录流**

```bash
cd frontend && pnpm build && pnpm dev
```
浏览器开登录页 → 看极光 + 玻璃卡 + 入场动效 → 实际登录跳转 dashboard。

- [ ] **Step 3: Commit** `feat(fe): R2 Login分屏hero(极光+玻璃卡+入场动效)`

---

# Slice R3 — 驾驶舱 ×4(Student/LabAdmin/Admin/Index)

### Task R3.1: StatCard 行 + 旧 StatCard 迁移 + aurora

**Files:**
- Modify: `frontend/src/views/dashboard/{Index,Student,LabAdmin,Admin}.vue`
- Delete: `frontend/src/components/charts/StatCard.vue`
- Modify: 上述 4 视图 import 改 `@/components/ui/StatCard`

- [ ] **Step 1: 4 视图顶部 stat 区改用 `ui/StatCard`**

每角色 dashboard 顶部指标行换 `<StatCard>`(value 接真实指标 count,带 trend/icon)。删 `charts/StatCard.vue`,grep 全仓确认无残留引用。

- [ ] **Step 2: 顶部加 aurora hero 带**

每 dashboard 顶部 `<PageHeader>` 区加一层弱 aurora 背景。

- [ ] **Step 3: build + 浏览器实测 3 角色**(student/labadmin/admin 登录看 count-up)

- [ ] **Step 4: Commit** `feat(fe): R3 驾驶舱StatCard行(count-up)+迁移旧StatCard+aurora`

### Task R3.2: ECharts 图表网格 + 活动流深色

**Files:**
- Modify: 4 dashboard 视图(图表区 `<GlowCard>` 包裹 + `useStagger` 错峰);活动流/列表深色

- [ ] **Step 1: 图表区包 GlowCard + data-stagger**

每个图表 `<GlowCard data-stagger>` 包裹,容器加 `useStagger` 触发错峰入场。活动流/热力/类目表深色 scoped 调。

- [ ] **Step 2: build + 浏览器实测图表深色 + 入场**

- [ ] **Step 3: Commit** `feat(fe): R3 驾驶舱图表网格深色+错峰入场+活动流`

### Task R3.3: R3 收尾

- [ ] vitest + build;过 frontend-design 复审(数据密集页**不加视差/错峰到表格**,守铁律 §6.1)

---

# Slice R4 — 设备三件(Index/Detail/Manage)

### Task R4.1: Device Index(卡片网格 + SegmentedControl 筛选)

**Files:** Modify `frontend/src/views/device/Index.vue`

- [ ] **Step 1: 重写** — 顶部 `<PageHeader>` + `<SegmentedControl>` 筛选(类目/状态/实验室,滑块动效)+ `<GlowCard>` 设备网格(每卡:StatusDot + 品牌/型号 + 规格 + 价格 + hover 抬升 + 错峰 `data-stagger`/`useStagger`)。列表/网格切换可选。
- [ ] **Step 2: build + 浏览器实测**(270 设备渲染、筛选滑块、hover)
- [ ] **Step 3: Commit** `feat(fe): R4 Device浏览(SegmentedControl筛选+GlowCard网格+错峰)`

### Task R4.2: Device Detail(hero + sticky 操作栏 + tabs)

**Files:** Modify `frontend/src/views/device/Detail.vue`

- [ ] **Step 1: 重写** — hero 头(`PageHeader` + 设备展示名 Space Grotesk + StatusDot + 关键规格 chip 行)+ sticky 操作栏(`GradientButton` 预约 / `GhostButton` 报修,吸顶毛玻璃)+ `<el-tabs>`(规格/预约日历/历史)深色调。预约日历沿用既有逻辑,样式深色。
- [ ] **Step 2: build + 实测**(从浏览点设备进详情,sticky 栏,tabs)
- [ ] **Step 3: Commit** `feat(fe): R4 Device详情(hero+sticky操作栏+tabs深色)`

### Task R4.3: Device Manage(管理暗表)

**Files:** Modify `frontend/src/views/device/Manage.vue`

- [ ] **Step 1: 重写** — `<PageHeader>` + 顶部 `GradientButton` 新增设备 + `<el-table>` 深色(行 hover 青色 tint)+ 状态 `<Tag>` + 批量操作 `GhostButton`。分页深色。
- [ ] **Step 2: build + 实测**(admin 看管理表)
- [ ] **Step 3: Commit** `feat(fe): R4 Device管理暗表(青行hover+批量操作)`

### Task R4.4: R4 收尾 — vitest + build + frontend-design 复审

---

# Slice R5 — 预约/审批/报修/推荐

### Task R5.1: Reservation Create(多步 stepper + 摘要 + 渐变提交)

**Files:** Modify `frontend/src/views/reservation/Create.vue`

- [ ] **Step 1: 重写** — `<el-steps>` 青色进度(选设备/选时段/确认)+ 主表单区 + 右侧 sticky `<GlowCard>` 实时摘要(设备/时段/时长/费用)+ 底部 `GradientButton` 提交 + `GhostButton` 上一步。逻辑零改。
- [ ] **Step 2: build + 实测**(完整建预约流)
- [ ] **Step 3: Commit** `feat(fe): R5 建预约(stepper+实时摘要+渐变提交)`

### Task R5.2: Reservation Mine + Detail(Timeline)

**Files:** Modify `reservation/Mine.vue`, `reservation/Detail.vue`

- [ ] **Step 1: Mine** — `<PageHeader>` + 预约卡片列表(每卡 StatusDot + 时段 + 设备 + 状态 Tag + 操作 GhostButton)+ 筛选 SegmentedControl(全部/待审/进行中/已结束)。`Detail` — `<Timeline>` 展示预约生命周期(创建→审批→签到→归还 / 超时取消分支)+ 详情 GlowCard + 相关操作。
- [ ] **Step 2: build + 实测**
- [ ] **Step 3: Commit** `feat(fe): R5 我的预约列表+预约详情Timeline`

### Task R5.3: Approval Pending(队列 + 行内操作)

**Files:** Modify `approval/Pending.vue`

- [ ] **Step 1: 重写** — `<PageHeader>` + 审批队列卡片列表(每卡:申请人/设备/时段/理由 + `GradientButton` 通过 / `GhostButton` 驳回 + 行内展开详情)。逻辑零改。
- [ ] **Step 2: build + 实测**(labadmin 审批)
- [ ] **Step 3: Commit** `feat(fe): R5 审批队列(行内通过/驳回)`

### Task R5.4: Repair 三件(Submit/Mine/AdminList)

**Files:** Modify `repair/Submit.vue`, `repair/Mine.vue`, `repair/AdminList.vue`

- [ ] **Step 1: Submit** — 报修表单(GlowCard 包 + GradientButton 提交)。`Mine` — 我的报修列表 + `<Timeline>` 处理进度。`AdminList` — 管理暗表(青行 hover + 状态 Tag + 处理操作)。
- [ ] **Step 2: build + 实测**(student 报修 → admin 处理)
- [ ] **Step 3: Commit** `feat(fe): R5 报修三件(提交表单+进度Timeline+管理暗表)`

### Task R5.5: Recommendation(卡片网格 + 理由 chips)

**Files:** Modify `recommendation/Index.vue`

- [ ] **Step 1: 重写** — `<PageHeader>`(冷启动时副标题提示)+ `<GlowCard>` 推荐网格(每卡:设备 + Score + "推荐理由" `<Tag>` chips 青色调 + hover 抬升 + 错峰)。逻辑零改。
- [ ] **Step 2: build + 实测**(student 看推荐,冷启动降级)
- [ ] **Step 3: Commit** `feat(fe): R5 推荐网格(理由chips+冷启动)`

### Task R5.6: R5 收尾 — vitest + build + frontend-design 复审

---

# Slice R6 — 收尾(Notification + User + 全局回归 + 截图)

### Task R6.1: Notification(列表 + 未读青条 + 空态)

**Files:** Modify `notification/Index.vue`

- [ ] **Step 1: 重写** — `<PageHeader>` + 顶部"全部已读"`GhostButton` + 通知列表(未读项左侧 2px 青条 + 类型 Tag + 时间 + 点击标记已读)+ `<EmptyState>` 空态。逻辑零改。
- [ ] **Step 2: build + 实测**(WS 推送到达 → 列表更新)
- [ ] **Step 3: Commit** `feat(fe): R6 通知列表(未读青条+空态)`

### Task R6.2: User Index(暗表 + 角色徽章 + 抽屉)

**Files:** Modify `user/Index.vue`

- [ ] **Step 1: 重写** — `<PageHeader>` + `GradientButton` 新增用户 + `<el-table>` 暗表(角色 `<Badge>` 青色调 + 状态 Tag)+ `GradientButton` 编辑 → `el-drawer` 深色管理抽屉。
- [ ] **Step 2: build + 实测**(sysadmin 管用户)
- [ ] **Step 3: Commit** `feat(fe): R6 用户管理暗表+角色徽章+抽屉`

### Task R6.3: 全局回归 + 删临时 + 截图归档

- [ ] **Step 1: 全量 vitest + build**

```bash
cd frontend && pnpm test && pnpm build
```
Expected: 全绿、build 干净。

- [ ] **Step 2: 删临时 `/ui-preview` 路由**(R1.6 若建)

- [ ] **Step 3: 浏览器冒烟 3 角色全流程**(吸取阶段2+3 "build 绿≠运行时正确"教训)
  - student:登录→驾驶舱→设备浏览/详情→建预约→推荐→我的预约→通知
  - labadmin:登录→驾驶舱→审批→报修管理→设备管理
  - sysadmin:登录→驾驶舱→用户管理→报修管理
  - 重点验:WS 推送、count-up、错峰入场、sticky 栏、滑块筛选、超时取消 demo(短 signin-grace)

- [ ] **Step 4: 三角色截图入 `docs/thesis/screenshots/`**(命名:`{role}-{page}.png`,如 `student-dashboard.png`、`labadmin-approval.png`、`login.png`)

- [ ] **Step 5: Commit** `feat(fe): R6 全局回归+3角色截图归档`

### Task R6.4: 终审 + 合并准备

- [ ] **Step 1: 过 `frontend-design`(或 impeccable,若已 reload)终审全分支**
- [ ] **Step 2: 后端确认零改动**(git diff 应只动 `frontend/` + `docs/thesis/screenshots/`)
- [ ] **Step 3: 用 superpowers:finishing-a-development-branch 收尾**(测→选项→合并/PR)**

---

## 风险预案(执行中触发)
- **EP 某组件暗色没盖到**(如 DatePicker popper 仍浅):R0.2 验收时补该 `--el-*` 变量;属 token 缺漏,不另开 slice。
- **`@vueuse/motion` 与 vue-router transition 冲突**:优先用 router `<transition>`,组件内入场才用 v-motion。
- **答辩机 `prefers-reduced-motion` 误开导致动效全无**:demo 前确认系统设置;铁律本就要求尊重该偏好。
- **270 设备卡片渲染卡顿**:Device Index 用虚拟滚动(`el-table-v2` 或自实现)或分页;R4.1 评估。
