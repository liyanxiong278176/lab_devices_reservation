import request from './request'
import type { DeviceVO } from '@/types/device'
import type { Page } from '@/types/common'

export type MaintenanceType = 'ROUTINE' | 'CALIBRATION' | 'SAFETY_CHECK'
export type MaintenanceIntervalUnit = 'DAY' | 'MONTH' | 'YEAR'
export type MaintenanceResult = 'PASSED' | 'FAILED'

export interface MaintenancePlanVO {
  id: number
  deviceId: number
  deviceName: string
  deviceAssetCode?: string | null
  collegeId: number | null
  planType: MaintenanceType
  title: string
  intervalValue: number
  intervalUnit: MaintenanceIntervalUnit
  dueDate: string
  downtimeStart?: string | null
  downtimeEnd?: string | null
  active: boolean
  temporarilyUnbookable: boolean
  unbookableReason?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface MaintenanceRecordVO {
  id: number
  planId: number
  deviceId: number
  collegeId: number | null
  cycleDueDate: string
  completedDate: string
  downtimeStart?: string | null
  downtimeEnd?: string | null
  result: MaintenanceResult
  notes?: string | null
  performedBy: number
  performedByName?: string | null
  evidenceAssetToken?: string | null
  evidenceName?: string | null
  evidenceContentType?: string | null
  evidenceSizeBytes?: number | null
  evidenceUrl?: string | null
  repairReportId?: number | null
  createdAt?: string | null
}

export interface MaintenancePage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

interface V2MaintenanceDevice {
  id: number
  name: string
  status: DeviceVO['status']
  brand?: string | null
  model?: string | null
  specs?: string | null
  image_url?: string | null
  category_id?: number | null
  category_name?: string | null
  lab_id?: number | null
  lab_name?: string | null
  college_id?: number | null
  college_name?: string | null
  need_approval: boolean
  max_reservation_days: number
  asset_code?: string | null
  maintenance_warning?: string | null
}

interface V2MaintenancePlan {
  id: number
  device_id: number
  device_name: string
  device_asset_code?: string | null
  college_id: number | null
  plan_type: MaintenanceType
  title: string
  interval_value: number
  interval_unit: MaintenanceIntervalUnit
  due_date: string
  downtime_start?: string | null
  downtime_end?: string | null
  active: boolean
  temporarily_unbookable: boolean
  unbookable_reason?: string | null
  created_at?: string | null
  updated_at?: string | null
}

interface V2MaintenanceRecord {
  id: number
  plan_id: number
  device_id: number
  college_id: number | null
  cycle_due_date: string
  completed_date: string
  downtime_start?: string | null
  downtime_end?: string | null
  result: MaintenanceResult
  notes?: string | null
  performed_by: number
  performed_by_name?: string | null
  evidence_asset_token?: string | null
  evidence_name?: string | null
  evidence_content_type?: string | null
  evidence_size_bytes?: number | null
  evidence_url?: string | null
  repair_report_id?: number | null
  created_at?: string | null
}

interface V2Upload {
  asset_token: string
  name: string
  content_type: string
  size_bytes: number
  url: string
}

const mapPlan = (row: V2MaintenancePlan): MaintenancePlanVO => ({
  id: row.id,
  deviceId: row.device_id,
  deviceName: row.device_name,
  deviceAssetCode: row.device_asset_code,
  collegeId: row.college_id,
  planType: row.plan_type,
  title: row.title,
  intervalValue: row.interval_value,
  intervalUnit: row.interval_unit,
  dueDate: row.due_date,
  downtimeStart: row.downtime_start,
  downtimeEnd: row.downtime_end,
  active: row.active,
  temporarilyUnbookable: row.temporarily_unbookable,
  unbookableReason: row.unbookable_reason,
  createdAt: row.created_at,
  updatedAt: row.updated_at,
})

const mapRecord = (row: V2MaintenanceRecord): MaintenanceRecordVO => ({
  id: row.id,
  planId: row.plan_id,
  deviceId: row.device_id,
  collegeId: row.college_id,
  cycleDueDate: row.cycle_due_date,
  completedDate: row.completed_date,
  downtimeStart: row.downtime_start,
  downtimeEnd: row.downtime_end,
  result: row.result,
  notes: row.notes,
  performedBy: row.performed_by,
  performedByName: row.performed_by_name,
  evidenceAssetToken: row.evidence_asset_token,
  evidenceName: row.evidence_name,
  evidenceContentType: row.evidence_content_type,
  evidenceSizeBytes: row.evidence_size_bytes,
  evidenceUrl: row.evidence_url,
  repairReportId: row.repair_report_id,
  createdAt: row.created_at,
})

export const listMaintenanceDevices = async (params: {
  page?: number
  pageSize?: number
  search?: string
} = {}): Promise<Page<DeviceVO>> => {
  const result = await request.get<unknown, MaintenancePage<V2MaintenanceDevice>>(
    '/maintenance-devices',
    {
      params: {
        page: params.page || 1,
        page_size: params.pageSize || 100,
        search: params.search?.trim() || undefined,
      },
    },
  )
  return {
    records: result.items.map((row): DeviceVO => ({
      id: row.id,
      name: row.name,
      status: row.status,
      brand: row.brand || undefined,
      model: row.model || undefined,
      specs: row.specs || undefined,
      imageUrl: row.image_url || undefined,
      categoryId: row.category_id ?? null,
      categoryName: row.category_name || undefined,
      labId: row.lab_id ?? null,
      labName: row.lab_name || undefined,
      collegeId: row.college_id ?? null,
      collegeName: row.college_name || undefined,
      needApproval: row.need_approval ? 1 : 0,
      maxReservationDays: row.max_reservation_days,
      assetCode: row.asset_code || undefined,
      maintenanceWarning: row.maintenance_warning || undefined,
    })),
    total: result.total,
    size: result.page_size,
    current: result.page,
    pages: result.pages,
    truncated: result.truncated,
  }
}

export const listMaintenancePlans = async (params: {
  page?: number
  pageSize?: number
  deviceId?: number
  active?: boolean | null
}) => {
  const page = await request.get<unknown, MaintenancePage<V2MaintenancePlan>>(
    '/maintenance-plans',
    {
      params: {
        page: params.page || 1,
        page_size: params.pageSize || 50,
        device_id: params.deviceId,
        active: params.active,
      },
    },
  )
  return { ...page, items: page.items.map(mapPlan) }
}

export const createMaintenancePlan = async (
  deviceId: number,
  payload: Omit<MaintenancePlanVO, 'id' | 'deviceId' | 'deviceName' | 'deviceAssetCode' | 'collegeId' | 'temporarilyUnbookable' | 'unbookableReason' | 'createdAt' | 'updatedAt'>,
) => {
  const row = await request.post<unknown, V2MaintenancePlan>(
    `/devices/${deviceId}/maintenance-plans`,
    toPlanPayload(payload),
  )
  return mapPlan(row)
}

export const updateMaintenancePlan = async (
  id: number,
  payload: Omit<MaintenancePlanVO, 'id' | 'deviceId' | 'deviceName' | 'deviceAssetCode' | 'collegeId' | 'temporarilyUnbookable' | 'unbookableReason' | 'createdAt' | 'updatedAt'>,
) => {
  const row = await request.put<unknown, V2MaintenancePlan>(
    `/maintenance-plans/${id}`,
    toPlanPayload(payload),
  )
  return mapPlan(row)
}

function toPlanPayload(payload: Parameters<typeof createMaintenancePlan>[1]) {
  return {
    plan_type: payload.planType,
    title: payload.title,
    interval_value: payload.intervalValue,
    interval_unit: payload.intervalUnit,
    due_date: payload.dueDate,
    downtime_start: payload.downtimeStart || null,
    downtime_end: payload.downtimeEnd || null,
    active: payload.active,
  }
}

export const listMaintenanceRecords = async (planId: number, page = 1) => {
  const result = await request.get<unknown, MaintenancePage<V2MaintenanceRecord>>(
    `/maintenance-plans/${planId}/records`,
    { params: { page, page_size: 20 } },
  )
  return { ...result, items: result.items.map(mapRecord) }
}

export const uploadMaintenanceEvidence = async (deviceId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request.post<unknown, V2Upload>(
    `/devices/${deviceId}/maintenance-evidence`,
    form,
  )
}

export const downloadMaintenanceEvidence = async (url: string, filename: string) => {
  const baseUrl = (request.defaults.baseURL ?? '').replace(/\/+$/, '')
  const endpoint = baseUrl && url.startsWith(`${baseUrl}/`) ? url.slice(baseUrl.length) : url
  const blob = await request.get<Blob, Blob>(endpoint, { responseType: 'blob' })
  const objectUrl = URL.createObjectURL(blob)
  const anchor = window.document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

export const completeMaintenanceCycle = async (
  planId: number,
  payload: {
    cycleDueDate: string
    completedDate: string
    result: MaintenanceResult
    notes?: string
    evidenceAssetToken?: string
  },
  idempotencyKey: string,
) => {
  const row = await request.post<unknown, V2MaintenanceRecord>(
    `/maintenance-plans/${planId}/records`,
    {
      cycle_due_date: payload.cycleDueDate,
      completed_date: payload.completedDate,
      result: payload.result,
      notes: payload.notes || null,
      evidence_asset_token: payload.evidenceAssetToken || null,
    },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
  return mapRecord(row)
}
