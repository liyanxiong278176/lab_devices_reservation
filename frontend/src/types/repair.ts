/** 报修状态（与后端 RepairStatus 一致）。 */
export type RepairStatus = 'PENDING' | 'PROCESSING' | 'RESOLVED' | 'COMPLETED' | 'REJECTED'
export type RepairPriority = 'NORMAL' | 'IMPORTANT' | 'URGENT'

/** 报修返回视图。 */
export interface RepairReportVO {
  id: number
  deviceId: number
  deviceName?: string
  reporterId: number
  reporterName?: string
  title: string
  description?: string
  imageUrls?: string[]
  status: RepairStatus
  handlerId?: number
  resolutionNote?: string
  createdAt?: string
  resolvedAt?: string
  priority: RepairPriority
  responseDueAt?: string
  resolveDueAt?: string
  userConfirmedAt?: string
  userConfirmationNote?: string
  closedAt?: string
}

/** 报修创建参数。 */
export interface RepairCreatePayload {
  deviceId: number
  title: string
  description?: string
  imageUrls?: string[]
  priority?: RepairPriority
}
