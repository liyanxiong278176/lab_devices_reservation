// ============================================================================
// echarts-dark-theme.ts — 'lab-dark' ECharts 主题
// ----------------------------------------------------------------------------
// 与 styles/theme.dark.scss 的深色 token 对齐(echarts theme 不认 CSS 变量,
// 故这里直接写 hex/rgba 字面量)。颜色 token 权威来源:
//   docs/superpowers/specs/2026-07-04-frontend-redesign-design.md §3
//
// 注册点:composables/useEcharts.ts → registerTheme('lab-dark', labDarkTheme)
// 消费点:components/charts/BaseChart.vue 默认 theme='lab-dark'。
//
// 设计:背景透明(由 .lab-card 承载底色),文字 --text-secondary(#9aa6b2),
// 坐标轴/分割线 --border-subtle(rgba 6% 白),tooltip 深色(--bg-elevated #161d2b),
// 数据色板青→蓝+状态语义 6 色循环。
// ============================================================================

export const labDarkTheme = {
  // 分类循环色板:青→蓝 + 状态语义(success/warning/danger/violet)
  color: ['#22d3ee', '#3b82f6', '#34d399', '#fbbf24', '#f87171', '#a78bfa'],

  // 卡片已提供底色,主题保持透明
  backgroundColor: 'transparent',

  // 全局文字(标题/坐标轴/图例的兜底色)= --text-secondary
  textStyle: {
    color: '#9aa6b2',
    fontFamily:
      'Inter, system-ui, -apple-system, "Segoe UI", "Helvetica Neue", sans-serif',
  },

  // ---- 标题(= --text-primary)--------------------------------------------
  title: {
    textStyle: { color: '#e6edf3', fontWeight: 600 },
    subtextStyle: { color: '#9aa6b2' },
  },

  // ---- 图例 -------------------------------------------------------------
  legend: {
    textStyle: { color: '#9aa6b2' },
    pageTextStyle: { color: '#9aa6b2' },
    pageIconColor: '#9aa6b2',
    pageIconInactiveColor: 'rgba(255, 255, 255, 0.16)',
  },

  // ---- 提示框(深色 elevated)--------------------------------------------
  tooltip: {
    backgroundColor: '#161d2b', // --bg-elevated
    borderColor: 'rgba(255, 255, 255, 0.10)', // --border-default
    borderWidth: 1,
    padding: 8,
    textStyle: { color: '#e6edf3', fontSize: 12 },
    axisPointer: {
      lineStyle: { color: 'rgba(255, 255, 255, 0.16)', type: 'dashed' }, // --border-strong
      crossStyle: { color: 'rgba(255, 255, 255, 0.16)' },
      label: { color: '#04141a', backgroundColor: '#22d3ee' }, // --text-on-accent / --accent
    },
  },

  // ---- 类目轴 -----------------------------------------------------------
  categoryAxis: {
    axisLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } }, // --border-subtle
    axisTick: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisLabel: { color: '#9aa6b2' },
    splitLine: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    splitArea: { show: false, areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
  },

  // ---- 数值轴(默认显示横向分割线)--------------------------------------
  valueAxis: {
    axisLine: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisTick: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisLabel: { color: '#9aa6b2' },
    splitLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    splitArea: { show: false, areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
  },

  // logAxis 沿用 valueAxis 外观
  logAxis: {
    axisLine: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisTick: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisLabel: { color: '#9aa6b2' },
    splitLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    splitArea: { show: false, areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
  },

  // timeAxis 沿用 categoryAxis 外观
  timeAxis: {
    axisLine: { show: true, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisTick: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    axisLabel: { color: '#9aa6b2' },
    splitLine: { show: false, lineStyle: { color: 'rgba(255, 255, 255, 0.06)' } },
    splitArea: { show: false, areaStyle: { color: ['rgba(255,255,255,0.02)', 'transparent'] } },
  },

  // ---- visualMap(热力图色阶文字)---------------------------------------
  visualMap: {
    textStyle: { color: '#9aa6b2' },
    inRange: { color: ['#243449', '#3b82f6', '#22d3ee'] }, // 软底→蓝→青(青→蓝渐变系)
  },

  // ---- 数据区域缩放(dataZoom)-------------------------------------------
  dataZoom: {
    backgroundColor: 'rgba(255, 255, 255, 0.02)',
    dataBackgroundColor: 'rgba(255, 255, 255, 0.06)',
    fillerColor: 'rgba(34, 211, 238, 0.12)',
    handleColor: '#22d3ee',
    handleSize: '80%',
    textStyle: { color: '#9aa6b2' },
  },

  // ---- 系列基色(被 option 显式 color 覆盖时的兜底)---------------------
  line: {
    itemStyle: { color: '#22d3ee' },
    lineStyle: { color: '#3b82f6', width: 2 },
    symbolSize: 6,
    symbol: 'emptyCircle',
  },
  bar: { itemStyle: { color: '#3b82f6' } },
  pie: { itemStyle: { color: '#22d3ee', borderColor: '#161d2b', borderWidth: 2 } },
  scatter: { itemStyle: { color: '#22d3ee' } },
  radar: {
    itemStyle: { color: '#22d3ee' },
    lineStyle: { color: '#3b82f6' },
    areaStyle: { color: 'rgba(34, 211, 238, 0.12)' },
  },
}
