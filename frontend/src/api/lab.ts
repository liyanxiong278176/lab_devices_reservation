import request from './request'
import type { Page } from '@/types/common'
import type { Lab } from '@/types/lab'
import type { LabWritePayload } from '@/types/lab'

/**
 * 实验室接口（对齐 LabController）。
 *
 * 仅用列表分页（设备管理页下拉选项需要）。
 *  - GET /labs?page&size → IPage<Lab>（需 SYS_ADMIN/LAB_ADMIN）
 */
interface V2Lab extends Lab {
  college_id?: number | null
  college_name?: string | null
  manager_id?: number | null
  manager_name?: string | null
}

interface V2LabPage {
  records: V2Lab[]
  total: number
  size: number
  current: number
  pages?: number
  truncated: boolean
}

const mapLab = (row: V2Lab): Lab => ({
  id: row.id,
  name: row.name,
  collegeId: row.college_id ?? null,
  collegeName: row.college_name ?? null,
  location: row.location,
  managerId: row.manager_id ?? null,
  managerName: row.manager_name ?? null,
  description: row.description,
  status: row.status,
  createdAt: row.createdAt,
  updatedAt: row.updatedAt,
})

export const listLabs = (page = 1, size = 100) =>
  request.get<unknown, V2LabPage>('/labs', { params: { page, size } }).then((data): Page<Lab> => ({
    records: data.records.map(mapLab),
    total: data.total,
    size: data.size,
    current: data.current,
    pages: data.pages,
    truncated: data.truncated,
  }))

const payload = (data: LabWritePayload) => ({
  college_id: data.collegeId,
  name: data.name,
  location: data.location || null,
  manager_id: data.managerId ?? null,
  description: data.description || null,
})

export const createLab = (data: LabWritePayload) =>
  request.post<unknown, Lab>('/labs', payload(data))

export const updateLab = (id: number, data: LabWritePayload) =>
  request.put<unknown, Lab>(`/labs/${id}`, payload(data))
