// Cal.com design tokens — source of truth: frontend/DESIGN.md + styles/theme.scss.
// Black (#111111) is the only primary CTA hue; blue (#3b82f6) is a sparing brand accent.
// Series use the DESIGN.md badge palette for categorical distinction.

export const INK = '#111111'
export const BLUE = '#3b82f6'
export const SUCCESS = '#10b981'
export const WARNING = '#f59e0b'
export const ERROR = '#ef4444'
export const VIOLET = '#8b5cf6'
export const ORANGE = '#fb923c'
export const MUTED = '#6b7280'
export const BODY = '#374151'
export const HAIRLINE = '#e5e7eb'
export const SURFACE_SOFT = '#f3f4f6'

/** 分类循环色板（饼/柱缺省顺序）。 */
export const SERIES_PALETTE = [INK, BLUE, SUCCESS, WARNING, ERROR, VIOLET, ORANGE]

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
