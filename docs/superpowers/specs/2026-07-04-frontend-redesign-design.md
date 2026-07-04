# 前端视觉重设计:科技深色(Linear/Vercel 风)

- 日期:2026-07-04
- 承接:阶段1-4 已合并 main(HEAD `0c13c70`,V5 种子数据)。前端 Vue3 + Element Plus + ECharts 已全功能,但视觉朴素。
- 范围:全量 ~18 页视觉重设计——配色/布局/组件/动效全面升级。**仅样式层,业务逻辑零改动**。
- 关联:`frontend/DESIGN.md`(旧 Cal.com 营销风契约,本次取代)、阶段2+3 spec `2026-07-02-phase2-3-highlights-and-frontend-design.md`。
- 分支:`feat/frontend-redesign-dark`。

---

## 1. 背景与根因诊断

当前前端外观"朴素/像线框图",**根因不是 CSS 坏了,是方向错**:

1. `DESIGN.md` 抄的是 Cal.com **营销页风**——黑白灰、零彩色、零阴影、零动效。这是营销 SaaS 的"高级感",但套在**后台管理/仪表盘**上 = 素、平、缺层级。
2. 登录页 = 灰底一张白卡,无 hero、无品牌存在感。
3. 后台 = Element Plus 默认容器 + 浅灰,无视觉层级、无密度节奏、无微交互。
4. `src/style.css`(紫色 Vite 脚手架残留)**未被 import**(`main.ts` 只引 `theme.scss`),死文件,本次删除。

重设计目标:**让平台一眼专业、现代、有冲击力**,贴合毕设答辩展示场景,同时保持 Element Plus 技术栈不变(不引 Tailwind,避免双轨迁移风险)。

## 2. 五项关键决策(brainstorm 已确认)

| # | 维度 | 决策 |
|---|---|---|
| 1 | 视觉方向 | **科技深色**(Linear/Vercel 风) |
| 2 | 重做范围 | **全量 ~18 页逐页重做** |
| 3 | 深色策略 | **全深色固定**(不做切换开关) |
| 4 | 主强调色 | **青/电光蓝**(cyan `#22d3ee` → blue `#3b82f6` 渐变) |
| 5 | 动效程度 | **全量丰富动效**(丰富但克制,遵守 §7 铁律) |

执行策略:**方案 A — Token 纵切**(先建深色设计系统层,再逐页套用)。契合项目既有 S0–S5 纵切 + 子代理逐任务模式,改动可控、零业务回归。

## 3. 设计 Token 体系(深色)

### 3.1 色板(全部映射到 `--el-*`,Element Plus 自动跟随)

| 用途 | 变量 | 值 |
|---|---|---|
| 应用底(最深) | `--bg-base` | `#0a0e14`(近黑带蓝调) |
| 卡片面 | `--bg-surface` | `#111722` |
| 抬升 / hover | `--bg-elevated` | `#161d2b` |
| 下沉(代码/侧栏) | `--bg-sunken` | `#060a10` |
| 发丝线-弱 | `--border-subtle` | `rgba(255,255,255,0.06)` |
| 发丝线-默认 | `--border-default` | `rgba(255,255,255,0.10)` |
| 发丝线-强 | `--border-strong` | `rgba(255,255,255,0.16)` |
| 正文/标题 | `--text-primary` | `#e6edf3` |
| 次要 | `--text-secondary` | `#9aa6b2` |
| 三级 | `--text-tertiary` | `#6b7785` |
| 强调上文字 | `--text-on-accent` | `#04141a` |
| **主强调** | `--accent` | `#22d3ee`(cyan-400) |
| 强调-亮 | `--accent-bright` | `#67e8f9` |
| 强调-深 | `--accent-deep` | `#0891b2` |
| **强调渐变** | `--grad-accent` | `linear-gradient(135deg,#22d3ee,#3b82f6)` |
| 强调辉光 | `--glow-accent` | `0 0 0 1px rgba(34,211,238,0.4),0 8px 30px rgba(34,211,238,0.18)` |
| 状态-success | `--status-success` | `#34d399` |
| 状态-warning | `--status-warning` | `#fbbf24` |
| 状态-danger | `--status-danger` | `#f87171` |
| 状态-info | `--status-info` | `#60a5fa` |

Element Plus 映射示例:`--el-color-primary: var(--accent)`;`--el-bg-color: var(--bg-surface)`;`--el-bg-color-page: var(--bg-base)`;`--el-text-color-primary/regular/secondary`、`--el-border-color*`、`--el-fill-color*` 全量覆盖。引入 `element-plus/theme-chalk/dark/css-vars.css` 作底,再用本项目 token 覆盖 EP 暗色变量。

### 3.2 字体(Cal Sans 无公开 web 字体,替换)

- **正文/UI**:Inter(400/500/600)—— `--font-sans`
- **展示标题**:Space Grotesk(600,几何科技感,Google Fonts 免费,近 Cal Sans 几何骨架)—— `--font-display`
- **数字/代码/设备号**:JetBrains Mono —— `--font-mono`
- 引入方式:**`@fontsource` 自托管**(离线、答辩不依赖外网),不用 Google Fonts CDN。

### 3.3 圆角 / 阴影 / 动效 token

- 圆角:控件 8px、卡片 12px、hero 面板 16px、pill 9999(沿用 Cal.com 层级,略收科技感)。
- 深色阴影:`inset 0 1px 0 rgba(255,255,255,0.04),0 8px 24px rgba(0,0,0,0.4)`;强调用 `--glow-accent`。
- 动效:`--ease-out-expo: cubic-bezier(.16,1,.3,1)`;`--d-fast 150ms / --d-med 280ms / --d-slow 500ms`。

## 4. 全局壳(MainLayout 深色重构)

- **侧栏**:`--bg-sunken`(比 main 更深),右侧 hairline。品牌字(Space Grotesk)+ **青色脉冲点** logo。菜单 active = 左侧 2px 青色指示条 + `--bg-elevated` + 青色图标;hover 抬升面。折叠宽度过渡。
- **顶栏**:半透明毛玻璃(`backdrop-filter: blur(12px)`)sticky,hairline 底。左 = 页标题/面包屑,右 = 通知铃(未读青点)+ 头像(在线青环)+ 退出。
- **主区**:`--bg-base`,内容容器居中,`<router-view>` 外裹 `<Transition name="page">`(fade + rise 8px)。
- **全局氛围光**:fixed 背景,左上角青色径向极弱辉光(alpha≈0.06),所有页面底层共氛围。

## 5. 通用组件库(`frontend/src/components/ui/`)

| 组件 | 职责 | 关键视觉 |
|---|---|---|
| `PageHeader` | 页头:展示标题 + 副标题 + 右侧 actions slot + 可选面包屑 | Space Grotesk 标题,底部 hairline |
| `Panel` / `GlowCard` | 通用卡片壳 | `--bg-surface` + hairline + hover 抬升 -2px + 辉光增强;可选顶部 1px 青色 accent 条 |
| `StatCard` | 驾驶舱指标卡 | 大数字 count-up + 趋势 delta(绿/红)+ sparkline + 青色 tint 图标 chip |
| `StatusDot` | 设备/预约状态点 | 脉冲点:IDLE 灰 / IN_USE 青脉冲 / MAINTENANCE 琥珀 / 故障红;附文字 |
| `GradientButton` | 主 CTA | 青→蓝渐变 + 辉光阴影 + hover 增亮 + press 收缩;替代默认黑按钮 |
| `GhostButton` / `TextButton` | 次级 | hairline / 纯文字,hover 青色 |
| `Skeleton` | 加载占位 | 深色 shimmer(非转圈) |
| `EmptyState` | 空态 | 图标 + 文案,弱辉光 |
| `SegmentedControl` | 切换组(筛选/tab) | 选中态 layout 动画滑块(青色 pill 在底槽滑动) |
| `Timeline` | 预约/报修进度 | 垂直时间轴 + 状态点 + 青色当前节点 |
| `Tag` / `Badge` | 标签 | 深色调过(semi-fill),状态语义色 |

全部走 token,scoped scss,不引 Tailwind。

## 6. 动效规范(丰富但克制)

- **页面进入**:`<Transition>` fade + rise 8px,280ms expo-out。
- **卡片错峰入场**:IntersectionObserver 触发,每卡 fade + rise,60ms stagger(`@vueuse/motion` 声明式)。
- **数字滚动**:StatCard count-up(requestAnimationFrame,1s expo)。
- **hover**:卡片抬升 + 辉光;按钮增亮 + 辉光扩散。
- **选中态**:菜单/SegmentedControl 滑块 layout 动画(transform)。
- **加载**:shimmer 骨架屏(表格/卡片),不用转圈。
- **氛围背景**:Login + Dashboard hero **慢速渐变极光**(纯 CSS keyframes,GPU only,12s 循环)。
- **图表**:ECharts 注册自定义深色主题 + 内置入场动画。
- **滚动视差**:hero 面板轻微 translateY,节流。

### 6.1 铁律(防 AI 味 / 花哨)
1. 全部走 `transform`/`opacity`(GPU),不触发 layout。
2. 单次入场 ≤500ms;**数据密集表格不加错峰/视差**(只留 hover)。
3. **尊重 `prefers-reduced-motion`**:命中则全关,只留即时态切换。提供 `v-reduced-motion` 指令统一管控。
4. 动效为引导注意力服务,不是炫技;**每页最多 1 个 signature 动效**。

## 7. 逐页处理(18 页,按处理族分组)

| 族 | 页 | 处理 |
|---|---|---|
| 登录 | Login | **分屏 hero**:左 = 品牌面板(极光渐变 + 产品名 Space Grotesk + tagline + 漂浮设备卡碎片);右 = 毛玻璃登录卡。入场动效 |
| 驾驶舱 | Dashboard Index/Student/LabAdmin/Admin | 顶部 4×StatCard(count-up + 趋势)+ ECharts 深色图表网格(利用率/热力/类目/报修)+ 活动流;顶部极光 |
| 设备浏览 | Device Index | SegmentedControl 筛选(滑块动效)+ GlowCard 网格(StatusDot + 品牌/型号 + hover 抬升),错峰入场 |
| 设备详情 | Device Detail | hero 头(展示名 + 状态 + 关键规格)+ sticky 操作栏(预约/报修 GradientButton)+ tabs(规格/预约日历/历史) |
| 设备管理 | Device Manage | 暗表 + 青色行 hover + 顶部 GradientButton 新增 + 批量操作 |
| 推荐 | Recommendation | 卡片网格 + "推荐理由" chips + 冷启动降级 + 错峰 |
| 建预约 | Reservation Create | 多步 stepper(青色进度)+ 实时摘要面板 + 渐变提交 |
| 我的/详情 | Reservation Mine + Detail | 垂直时间轴(状态点 + 青色当前节点)+ 详情卡 |
| 审批 | Approval Pending | 队列列表 + 通过/驳回(Gradient/Ghost)+ 行内展开 |
| 报修 | Repair Submit/Mine/AdminList | 表单 + 状态时间轴 + 管理暗表 |
| 通知 | Notification | 列表 + 未读青色条 + 标记已读 + 空态 |
| 用户 | User Index | 暗表 + 角色徽章 + 管理抽屉 |

## 8. 技术栈增量

- **字体**:`@fontsource` 自托管 Inter + Space Grotesk + JetBrains Mono(离线、答辩稳定)。
- **Element Plus 暗色**:`main.ts` 加 `import 'element-plus/theme-chalk/dark/css-vars.css'`,挂载时 `document.documentElement.classList.add('dark')`。
- **ECharts 深色主题**:在 `composables/useEcharts.ts` 注册自定义深色主题 JSON,所有图表默认用之。
- **动效库**:`@vueuse/motion`(声明式入场/错峰)+ `@vueuse/core`(`useIntersectionObserver`、`useTransition` 做 count-up)。Vue 原生、体积小。
- **删除** 死文件 `src/style.css`(未被 import,紫色 Vite 脚手架残留)。
- **不引** Tailwind(token + scoped scss,栈干净,避免与 Element Plus 双轨)。
- 全部 token 经 `--el-*` 映射,Element Plus 组件自动继承深色。

## 9. 切片计划(纵切,子代理逐任务 + 过 review)

| Slice | 内容 | 验收 |
|---|---|---|
| **R0 基建** | `theme.dark.scss` 全量 token + `@fontsource` 字体 + EP 暗色 css-vars + `html.dark` + ECharts 深色主题注册 + 删 style.css + 全局氛围光 + MainLayout 深色重构(§4)+ page transition 基建 + `v-reduced-motion` 指令 | 全站已变深色骨架,vitest 零回归 |
| **R1 组件库** | §5 全部组件 + §6 动效基建(@vueuse/motion 接入 + count-up composable + shimmer) | 组件可独立渲染,vitest 绿 |
| **R2 登录** | 分屏 aurora hero + 玻璃卡 + 入场 | 浏览器实测 |
| **R3 驾驶舱×4** | StatCard 行(count-up)+ ECharts 深色图 + 热力 + 活动流 + aurora | 3 角色实测 |
| **R4 设备三件** | Index 网格(stagger)+ Detail sticky + Manage 暗表 | 实测 |
| **R5 预约/审批/报修/推荐** | Create stepper / Mine+Detail 时间轴 / Approval 队列 / Repair 三页 / Recommend 网格 | 实测 |
| **R6 收尾** | Notification + User + 全局回归(pnpm build + vitest + 3 角色冒烟 + 截图入 `docs/thesis/screenshots`) | 截图归档 |

每 slice:**子代理实现 → 过 `frontend-design` 复审防 AI 味(或 `impeccable`,待用户 `/reload-plugins` 装上后切换)→ 独立验证**。改的全是样式层,业务逻辑零改动 → 后端 70 测试不受影响。

## 10. 风险与取舍

| 风险 | 缓解 |
|---|---|
| 深色 + 丰富动效易显 AI 味/花哨 | §6.1 铁律;每 slice 过 frontend-design/impeccable 复审 |
| Element Plus 暗色覆盖不全(部分组件仍浅) | R0 验收时逐组件扫 EP 暗色 css-vars 全量覆盖;补 `--el-*` 缺漏 |
| `@fontsource` 字体包体积 | 仅引需要的 weight(Inter 400/500/600、Space Grotesk 600、JetBrains Mono 400) |
| 丰富动效在低性能机/答辩机卡顿 | 全 GPU 属性 + reduced-motion 兜底 + 表格类页面不加动效 |
| 全量 18 页工作量大 | 纵切 7 slice 逐片交付验收,每片独立可演示 |
| 视觉重做撞后端常驻开发 | 子代理只动 `frontend/`,不碰 `docker compose`/`spring-boot:run`/java 进程(项目既有规矩) |

## 11. 验收标准(DoD)

- **视觉**:全站深色科技风,青电光蓝强调;登录 hero + 驾驶舱为 signature 页,有 aurora + count-up + 入场动效。
- **一致性**:所有页面用统一 token + 通用组件库,无散落硬编码色值。
- **无 AI 味**:过 frontend-design(或 impeccable)复审,动效守 §6.1 铁律。
- **零业务回归**:前端 vitest 全绿、`pnpm build` 干净;后端 70 测试不受影响。
- **运行时验收**:浏览器冒烟 3 角色全流程(login → 驾驶舱 → 设备浏览/预约/审批/报修 → 通知),截图入 `docs/thesis/screenshots/`(吸取阶段2+3 "build 绿 ≠ 运行时正确" 教训)。
- **可答辩**:配色/动效/组件取舍能在论文与答辩中讲清(深色科技定位、青强调、动效铁律、Token 纵切工程化)。

## 12. 与既有实现关系

- 取代 `frontend/DESIGN.md`(Cal.com 营销风)→ 新增 `frontend/DESIGN.dark.md` 作新设计源真相(本 spec 的精简版),保留旧 DESIGN.md 作历史。
- `theme.scss` → 重构为 `theme.dark.scss`(全量深色 token),`main.ts` 切换 import。
- 业务逻辑(Service/Mapper/Controller/MQ)**零改动**;仅 Vue 视图与样式层。
- 截图产出同时服务于毕设答辩(阶段4 `docs/thesis/screenshots/` 原本就缺)。
