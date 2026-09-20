import request from './request'
import type { Page } from '@/types/common'
import type { RepairCreatePayload, RepairReportVO, RepairStatus } from '@/types/repair'

interface V2Repair {
  id: number
  device_id: number
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
}

interface V2RepairPage {
  items: V2Repair[]
  total: number
  page: number
  page_size: number
  next_cursor?: number | null
  has_more?: boolean
}

function mapRepair(row: V2Repair): RepairReportVO {
  return {
    id: row.id,
    deviceId: row.device_id,
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
  })

export const myRepairs = (page = 1, size = 10, cursor?: number | null) =>
  request
    .get<unknown, V2RepairPage>('/repair-reports/mine', { params: { page, size, cursor: cursor || undefined } })
    .then((data): Page<RepairReportVO> => ({
      records: data.items.map(mapRepair),
      total: data.total,
      size: data.page_size,
      current: data.page,
      pages: Math.ceil(data.total / data.page_size),
      nextCursor: data.next_cursor,
      hasMore: data.has_more,
    }))

export const listRepairs = (status: RepairStatus | '' = '', page = 1, size = 10, cursor?: number | null) =>
  request
    .get<unknown, V2RepairPage>('/repair-reports', {
      params: { status: status || undefined, page, size, cursor: cursor || undefined },
    })
    .then((data): Page<RepairReportVO> => ({
      records: data.items.map(mapRepair),
      total: data.total,
      size: data.page_size,
      current: data.page,
      pages: Math.ceil(data.total / data.page_size),
      nextCursor: data.next_cursor,
      hasMore: data.has_more,
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
