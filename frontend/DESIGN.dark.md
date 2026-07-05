# DESIGN.dark — 实验室预约系统深色设计源真相

> 版本:1.0(2026-07-04,取代 `DESIGN.md` Cal.com 营销风)
> 方向:科技深色(Linear/Vercel 风)+ 青电光蓝强调 + 丰富但克制动效。
> 权威详尽规格见 `docs/superpowers/specs/2026-07-04-frontend-redesign-design.md`;本文件是日常写样式的速查精简版。

## 1. 色板(全量 token 在 `src/styles/theme.dark.scss`)

| token | 值 | 用途 |
|---|---|---|
| `--bg-base` | `#0a0e14` | 应用底(主区) |
| `--bg-sunken` | `#060a10` | 侧栏(更深,下沉) |
| `--bg-surface` | `#111722` | 卡片面 |
| `--bg-elevated` | `#161d2b` | 抬升/hover |
| `--border-subtle/default/strong` | `rgba(255,255,255,.06/.10/.16)` | 发丝线三档 |
| `--text-primary` | `#e6edf3` | 标题/正文 |
| `--text-secondary` | `#9aa6b2` | 次要 |
| `--text-tertiary` | `#6b7785` | 三级(勿进表单标签/表格单元) |
| `--text-on-accent` | `#04141a` | 压在青强调上的深字 |
| `--accent` | `#22d3ee` | 主强调(青) |
| `--accent-bright/deep` | `#67e8f9 / #0891b2` | 强调亮/深 |
| `--grad-accent` | `linear-gradient(135deg,#22d3ee,#3b82f6)` | 主 CTA 渐变 |
| `--glow-accent` | `0 0 0 1px rgba(34,211,238,.4),0 8px 30px rgba(34,211,238,.18)` | 强调辉光 |
| `--status-success/warning/danger/info` | `#34d399 / #fbbf24 / #f87171 / #60a5fa` | 状态语义 |

**铁律**:`--accent` 是唯一强调色。不引竞争色相做 CTA。状态色只表语义(IDLE/进行/故障…),不做装饰强调。

## 2. 字体

- `--font-sans` Inter(正文/UI/按钮)
- `--font-display` Space Grotesk 600(展示标题/品牌/页头)
- `--font-mono` JetBrains Mono(数字/设备号/代码)
- 自托管(`@fontsource`),离线可用,答辩不依赖外网。

## 3. 圆角 / 阴影

- 控件 8px、卡片 12px、hero 面板 16px、pill 9999。
- 深色软阴影 `inset 0 1px 0 rgba(255,255,255,.04),0 8px 24px rgba(0,0,0,.4)`;强调用 `--glow-accent`。

## 4. Element Plus 暗色覆盖

全量 `--el-*` 映射到上述 token(见 `theme.dark.scss`)。要点:
- `--el-color-primary = --accent`(及衍生 light/dark 档)。
- 主按钮:`--el-button-text-color = --text-on-accent`(深字压青底,WCAG AA)。`.el-button--primary { color: var(--text-on-accent) !important }`。
- ⚠️ **EP 表格 `--el-table-*` 尚未桥接**(延后 R4,设备/用户/审批/报修管理暗表 slice 一并做)。R4 前表格会有冷灰条纹偏色,已知。

## 5. 动效规范(丰富但克制,`src/styles/_motion.scss`)

- 缓动 `--ease-out-expo cubic-bezier(.16,1,.3,1)`;时长 `--d-fast 150ms / --d-med 280ms / --d-slow 500ms`。
- 页面切换:`<transition name="page">`(fade + rise 8px,280ms)。
- 卡片错峰:`useStagger`(IntersectionObserver,60ms stagger,`data-stagger` 标记)。初始 `opacity:0` 由 `html.js [data-stagger]` gate(JS 失败则内容可见)。
- 数字滚动:`useCountUp`(rAF + easeOutExpo,1s)。
- 氛围光:全局 `.aurora-bg`(fixed,极弱青径向辉光,alpha ~0.18→0.28 慢循环 12s)。认证页主区透明以透出。
- 加载:shimmer 骨架屏(非转圈)。

### 5.1 铁律(防 AI 味/花哨)
1. 全 GPU 属性(`transform`/`opacity`),不触发 layout。(`.shimmer` 用 background-position 仅 repaint,可接受。)
2. 单次入场 ≤500ms(count-up 例外 1s)。**数据密集表格不加错峰/视差**,只留 hover。
3. **尊重 `prefers-reduced-motion`**:CSS 全局守卫(`_motion.scss` 末尾)+ `useStagger`/`useCountUp` 短路 + `v-reduced-motion` 指令。命中则动效全关,只留即时态。
4. 每页最多 1 个 signature 动效。

## 6. 组件库(`src/components/ui/`,R1 建)

PageHeader / Panel / GlowCard / StatCard / StatusDot / GradientButton / GhostButton / TextButton / Skeleton / EmptyState / SegmentedControl / Timeline / Tag / Badge —— 14 件,全部走 token。

## 7. Do / Don't

**Do**
- 强调用 `--accent` / `--grad-accent` / `--glow-accent`;状态用 `--status-*`。
- 标题 Space Grotesk,正文 Inter,数字 JetBrains Mono。
- 卡片用 Panel/GlowCard;深色软阴影 + hairline。
- 动效走 `useStagger`/`useCountUp`/`<transition>`,守 reduced-motion。

**Don't**
- 不引紫/粉/橙做主色(状态语义除外)。
- 不用纯白字压青底(用 `--text-on-accent`)。
- 不在表格页加视差/错峰/丰富入场(只 hover)。
- 不硬编码 hex(用 token)。
