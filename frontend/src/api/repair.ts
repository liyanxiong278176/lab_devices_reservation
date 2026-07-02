import request from './request'
import type { Page } from '@/types/common'
import type { RepairCreatePayload, RepairReportVO, RepairStatus } from '@/types/repair'

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
  request.post<unknown, number>('/repair-reports', data)

export const myRepairs = (page = 1, size = 10) =>
  request.get<unknown, Page<RepairReportVO>>('/repair-reports/mine', { params: { page, size } })

export const listRepairs = (status: RepairStatus | '' = '', page = 1, size = 10) =>
  request.get<unknown, Page<RepairReportVO>>('/repair-reports', {
    params: { status: status || undefined, page, size },
  })

export const takeRepair = (id: number) =>
  request.post<unknown, void>(`/repair-reports/${id}/take`)

// resolve/reject 均用 @RequestBody RepairHandleDTO { resolutionNote }
export const resolveRepair = (id: number, resolutionNote: string) =>
  request.post<unknown, void>(`/repair-reports/${id}/resolve`, { resolutionNote })

export const rejectRepair = (id: number, resolutionNote: string) =>
  request.post<unknown, void>(`/repair-reports/${id}/reject`, { resolutionNote })
