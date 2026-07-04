// Lab 深色主题色板 — source of truth: styles/theme.dark.scss + echarts-dark-theme.ts。
// R0.3 重调:青→蓝渐变系 + 状态语义色,与深色 token 对齐。
// 导出名保持不变(Bar/Line/Pie/HeatmapWidget + 状态记录均按名引用),仅替换值。
//
// 主强调青色(#22d3ee = --accent)取代旧的黑色 INK,作为热力峰值/已完成状态;
// 蓝色(#3b82f6)保留为渐变中段;状态色对齐 --status-* token。

export const INK = '#22d3ee' // 主强调青(--accent);热力峰值 / 已完成
export const BLUE = '#3b82f6' // 渐变中段蓝
export const SUCCESS = '#34d399' // --status-success
export const WARNING = '#fbbf24' // --status-warning
export const ERROR = '#f87171' // --status-danger
export const VIOLET = '#a78bfa' // 紫色分类色
export const ORANGE = '#fb923c' // 爽约(NO_SHOW)语义色(保留,不进 SERIES_PALETTE 循环)
export const MUTED = '#9aa6b2' // --text-secondary(坐标轴标签)
export const BODY = '#e6edf3' // --text-primary(饼图标签)
export const HAIRLINE = 'rgba(255, 255, 255, 0.06)' // --border-subtle(轴线/分割线)
export const SURFACE_SOFT = '#243449' // 深色软底(热力图低值端)

/** 分类循环色板(饼/柱缺省顺序):青→蓝 + 状态语义,6 色。 */
export const SERIES_PALETTE = [INK, BLUE, SUCCESS, WARNING, ERROR, VIOLET]

// ---- 设备状态（deviceStatus）----
export const DEVICE_STATUS_ORDER = ['IDLE', 'IN_USE', 'MAINTENANCE']
export const DEVICE_STATUS_LABELS: Record<string, string> = {
  IDLE: '空闲',
  IN_USE: '使用中',
  MAINTENANCE: '维护中',
}
export const DEVICE_STATUS_COLORS: Record<string, string> = {
  IDLE: SUCCESS,
  IN_USE: BLUE,
  MAINTENANCE: WARNING,
}

// ---- 报修状态（repairStats）----
export const REPAIR_STATUS_ORDER = ['PENDING', 'PROCESSING', 'RESOLVED', 'REJECTED']
export const REPAIR_STATUS_LABELS: Record<string, string> = {
  PENDING: '待处理',
  PROCESSING: '处理中',
  RESOLVED: '已解决',
  REJECTED: '已驳回',
}
export const REPAIR_STATUS_COLORS: Record<string, string> = {
  PENDING: WARNING,
  PROCESSING: BLUE,
  RESOLVED: SUCCESS,
  REJECTED: ERROR,
}

// ---- 预约状态（myReservationsByStatus）----
export const RESERVATION_STATUS_ORDER = [
  'PENDING',
  'APPROVED',
  'COMPLETED',
  'REJECTED',
  'CANCELLED',
  'VIOLATED',
  'NO_SHOW',
]
export const RESERVATION_STATUS_LABELS: Record<string, string> = {
  PENDING: '待审批',
  APPROVED: '已通过',
  COMPLETED: '已完成',
  REJECTED: '已拒绝',
  CANCELLED: '已取消',
  VIOLATED: '违规',
  NO_SHOW: '爽约',
}
export const RESERVATION_STATUS_COLORS: Record<string, string> = {
  PENDING: WARNING,
  APPROVED: SUCCESS,
  COMPLETED: INK,
  REJECTED: ERROR,
  CANCELLED: MUTED,
  VIOLATED: ERROR,
  NO_SHOW: ORANGE,
}

/** 通用图表数据点（可带语义色）。 */
export interface ChartDatum {
  name: string
  value: number
  color?: string
}

/**
 * 把后端 Map<String,Long> 的状态分布转成饼/柱可消费的 ChartDatum[]：
 * 按 statusOrder 固定顺序输出，缺失或 0 的状态跳过（避免空切片/空柱），
 * 并附加语义颜色与中文标签。
 */
export function toStatusData(
  map: Record<string, number> | undefined | null,
  order: string[],
  labels: Record<string, string>,
  colors: Record<string, string>,
): ChartDatum[] {
  if (!map) return []
  return order
    .filter((k) => (map[k] ?? 0) > 0)
    .map((k) => ({ name: labels[k] ?? k, value: map[k], color: colors[k] }))
}
