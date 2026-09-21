/** 报修状态（与后端 RepairStatus 一致）。 */
export type RepairStatus = 'PENDING' | 'PROCESSING' | 'RESOLVED' | 'REJECTED'

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
}

/** 报修创建参数。 */
export interface RepairCreatePayload {
  deviceId: number
  title: string
  description?: string
  imageUrls?: string[]
}
