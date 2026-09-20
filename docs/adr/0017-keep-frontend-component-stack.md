# ADR-0017：保留现有 Vue/Element Plus 前端基础栈

- 状态：已接受
- 日期：2026-08-26
- 决策人：项目负责人

## 决策

前端继续使用 Vue 3、Vite、TypeScript、Element Plus、Pinia、ECharts、SockJS/STOMP 相关能力。重构通过 design tokens、业务组件、布局、状态模型和页面交互完成，不在本次项目中整体替换组件库。

Element Plus 负责稳定的表单、表格、弹窗、日期和无障碍基础能力；项目自定义组件负责设备卡片、日历占用块、审批工作台、Agent 步骤、引用面板、确认卡片和数据驾驶舱视觉。

## 影响

- 可以降低前端重写后的功能回归和学习成本。
- 需要覆盖 Element Plus 默认样式，避免页面退化为普通模板。
- 设计令牌必须贯穿 Element Plus 变量、自研组件和 ECharts 主题，不能只修改单个页面。
