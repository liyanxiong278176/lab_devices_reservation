import request from './request'

/**
 * 驾驶舱富指标接口（对齐 DashboardController / Dashboard*VO）。
 *
 * 关键契约：
 *  - GET /dashboard/overview?groupBy=device|category&days=30  → DashboardOverviewVO（管理员视角）
 *  - GET /dashboard/me                                          → DashboardMeVO（学生/个人视角）
 *  - GET /dashboard/summary                                     → 概要（旧桩，保留兼容）
 *
 * heatmap 为稀疏列表 [{dayOfWeek,hour,count}]（DAYOFWEEK 1=周日..7=周六；hour 0..13 对应 08:00..21:00），
 * 缺失项视为 0，前端需自行拼成 7×14 全网格。
 */

// ---- Overview（LAB_ADMIN / SYS_ADMIN）----
export interface UtilizationItemVO {
  /** 聚合键，如 "device:1" 或 "category:3" */
  key: string
  /** 展示名（设备名 / 类目名） */
  label: string
  occupiedSlots: number
  availableSlots: number
  /** 利用率 = occupied / available（available=0 时为 0） */
  utilizationRate: number
}

export interface CategoryDistItemVO {
  categoryId: number
  categoryName: string
  deviceCount: number
}

export interface ReservationTrendItemVO {
  /** ISO 日期，如 "2026-07-03" */
  date: string
  count: number
}

export interface HeatmapCellVO {
  /** MySQL DAYOFWEEK：1=周日 .. 7=周六 */
  dayOfWeek: number
  /** 相对 work-start 的小时偏移，0..13 对应 08:00..21:00 */
  hour: number
  count: number
}

export interface DashboardCardsVO {
  todayReservations: number
  pendingApprovals: number
  /** 近 7 天 VIOLATED + NO_SHOW 数 */
  weeklyViolations: number
}

export interface DashboardOverviewVO {
  /** IDLE / IN_USE / MAINTENANCE → count */
  deviceStatus: Record<string, number>
  trend30d: ReservationTrendItemVO[]
  utilization: UtilizationItemVO[]
  heatmap: HeatmapCellVO[]
  categoryDist: CategoryDistItemVO[]
  /** PENDING / PROCESSING / RESOLVED / REJECTED → count */
  repairStats: Record<string, number>
  cards: DashboardCardsVO
}

// ---- Me（STUDENT / 个人）----
export interface MyCategoryItemVO {
  categoryId: number
  categoryName: string
  count: number
}

export interface DashboardMeVO {
  /** PENDING / APPROVED / ... → count */
  myReservationsByStatus: Record<string, number>
  myTrend30d: ReservationTrendItemVO[]
  myCategoryDist: MyCategoryItemVO[]
  unreadCount: number
  myRepairCount: number
}

export const dashboardOverview = (
  params: { groupBy?: 'device' | 'category'; days?: number } = {},
) => request.get<unknown, DashboardOverviewVO>('/dashboard/overview', { params })

export const dashboardMe = () => request.get<unknown, DashboardMeVO>('/dashboard/me')

/** 旧概要接口（保留兼容，S4 之前已存在）。 */
export const summary = () => request.get<unknown, unknown>('/dashboard/summary')
