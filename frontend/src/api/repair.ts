import request from './request'
import type { Page } from '@/types/common'
import type {
  RepairCreatePayload,
  RepairPriority,
  RepairReportVO,
  RepairStatus,
} from '@/types/repair'

interface V2Repair {
  id: number
  device_id: number
  reservation_id?: number | null
  device_name: string
  reporter_id: number
  reporter_name?: string | null
  title: string
  description?: string | null
  image_urls?: string[] | null
  status: RepairStatus
  handler_id?: number | null
  resolution_note?: string | null
  created_at?: string
  resolved_at?: string | null
  priority?: RepairPriority
  response_due_at?: string | null
  resolve_due_at?: string | null
  user_confirmed_at?: string | null
  user_confirmation_note?: string | null
  closed_at?: string | null
}

interface V2RepairPage {
  items: V2Repair[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

function mapRepair(row: V2Repair): RepairReportVO {
  return {
    id: row.id,
    deviceId: row.device_id,
    reservationId: row.reservation_id ?? undefined,
    deviceName: row.device_name,
    reporterId: row.reporter_id,
    reporterName: row.reporter_name || undefined,
    title: row.title,
    description: row.description || undefined,
    imageUrls: row.image_urls || undefined,
    status: row.status,
    handlerId: row.handler_id || undefined,
    resolutionNote: row.resolution_note || undefined,
    createdAt: row.created_at,
    resolvedAt: row.resolved_at || undefined,
    priority: row.priority || 'NORMAL',
    responseDueAt: row.response_due_at || undefined,
    resolveDueAt: row.resolve_due_at || undefined,
    userConfirmedAt: row.user_confirmed_at || undefined,
    userConfirmationNote: row.user_confirmation_note || undefined,
    closedAt: row.closed_at || undefined,
  }
}

/**
 * 报修接口（对齐 RepairReportController）。
 *
 * 关键契约：
 *  - POST /repair-reports                → 用户提交（body RepairCreateDTO）
 *  - GET  /repair-reports/mine?page&size → 我的报修
 *  - GET  /repair-reports?status&page&size → 管理员列表（需 repair:handle，按自辖 lab 范围）
 *  - POST /repair-reports/{id}/take      → 受理（PENDING→PROCESSING，设备 MAINTENANCE）
 *  - POST /repair-reports/{id}/resolve   → 解决（body RepairHandleDTO { resolutionNote }）
 *  - POST /repair-reports/{id}/reject    → 驳回（body RepairHandleDTO { resolutionNote }）
 */
export const createRepair = (data: RepairCreatePayload) =>
  request.post<unknown, RepairReportVO>('/repair-reports', {
    device_id: data.deviceId,
    title: data.title,
    description: data.description,
    image_urls: data.imageUrls,
    priority: data.priority || 'NORMAL',
  })

export const uploadRepairImage = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request.post<unknown, { url: string }>('/repair-uploads', body)
}

export const myRepairs = (page = 1, size = 10) =>
  request
    .get<unknown, V2RepairPage>('/repair-reports/mine', { params: { page, size } })
    .then((data): Page<RepairReportVO> => ({
      records: data.items.map(mapRepair),
      total: data.total,
      size: data.page_size,
      current: data.page,
      pages: data.pages,
      truncated: data.truncated,
    }))

export const listRepairs = (status: RepairStatus | '' = '', page = 1, size = 10) =>
  request
    .get<unknown, V2RepairPage>('/repair-reports', {
      params: { status: status || undefined, page, size },
    })
    .then((data): Page<RepairReportVO> => ({
      records: data.items.map(mapRepair),
      total: data.total,
      size: data.page_size,
      current: data.page,
      pages: data.pages,
      truncated: data.truncated,
    }))

export const takeRepair = (id: number) =>
  request.post<unknown, void>(`/repair-reports/${id}/take`)

// resolve/reject 均用 @RequestBody RepairHandleDTO { resolutionNote }
export const resolveRepair = (id: number, resolutionNote: string) =>
  request.post<unknown, void>(`/repair-reports/${id}/resolve`, {
    resolution_note: resolutionNote,
  })

export const rejectRepair = (id: number, resolutionNote: string) =>
  request.post<unknown, void>(`/repair-reports/${id}/reject`, {
    resolution_note: resolutionNote,
  })

export const confirmRepair = (id: number, confirmed: boolean, note?: string) =>
  request.post<unknown, RepairReportVO>(`/repair-reports/${id}/confirm`, {
    confirmed,
    note,
  })

export interface RepairWorklogVO {
  id: number
  report_id: number
  operator_id: number
  status: string
  content: string
  image_urls?: string[] | null
  created_at?: string
}

export const repairWorklogs = (id: number) =>
  request.get<unknown, RepairWorklogVO[]>(`/repair-reports/${id}/worklogs`)
