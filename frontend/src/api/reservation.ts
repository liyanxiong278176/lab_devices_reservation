import request from './request'
import type { Page } from '@/types/common'
import type {
  ReservationCreatePayload,
  ReservationCreateResultVO,
  ReservationHandoverStatus,
  ReservationPreflightVO,
  ReservationQuery,
  ReservationStatus,
  ReservationVO,
} from '@/types/reservation'

interface V2Reservation {
  id: number
  device_id: number
  device_name: string
  user_id: number
  purpose?: string
  purpose_category?: ReservationVO['purposeCategory']
  project_reference?: string | null
  start_date: string
  end_date: string
  dates: string[]
  status: ReservationStatus
  batch_id?: string | null
  need_approval: boolean
  created_at?: string
  check_in_at?: string | null
  check_out_at?: string | null
  device_asset_code?: string | null
  device_lab_name?: string | null
  requires_handover?: boolean
  handover_status?: ReservationHandoverStatus | null
  safety_required?: boolean
  safety_acknowledged?: boolean
  safety_document_version?: string | null
  reject_reason?: string | null
  inspection_condition?: 'NORMAL' | 'DAMAGED' | 'MISSING' | null
  inspection_note?: string | null
  handover_image_urls?: string[]
  return_image_urls?: string[]
  accessory_snapshot?: string[]
  handover_checklist?: ReservationVO['handoverChecklist']
  return_checklist?: ReservationVO['returnChecklist']
  fault_repair_id?: number | null
}

interface V2ReservationPage {
  items: V2Reservation[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

export interface ReservationFeedbackVO {
  id: number
  reservation_id: number
  device_id: number
  user_id: number
  rating: number
  comment?: string | null
  created_at?: string | null
}

function mapReservation(item: V2Reservation): ReservationVO {
  return {
    id: item.id,
    userId: item.user_id,
    deviceId: item.device_id,
    deviceName: item.device_name,
    purpose: item.purpose || '',
    purposeCategory: item.purpose_category || 'OTHER',
    projectReference: item.project_reference || undefined,
    startDate: item.start_date,
    endDate: item.end_date,
    dates: item.dates,
    startTime: `${item.start_date}T00:00:00`,
    endTime: `${item.end_date}T23:59:59`,
    slotCount: item.dates.length,
    status: item.status,
    createdAt: item.created_at,
    checkInAt: item.check_in_at || undefined,
    checkOutAt: item.check_out_at || undefined,
    rejectReason: item.reject_reason || undefined,
    inspectionCondition: item.inspection_condition || undefined,
    inspectionNote: item.inspection_note || undefined,
    deviceAssetCode: item.device_asset_code || undefined,
    deviceLabName: item.device_lab_name || undefined,
    requiresHandover: Boolean(item.requires_handover),
    handoverStatus: item.handover_status || 'NOT_REQUIRED',
    safetyRequired: Boolean(item.safety_required),
    safetyAcknowledged: Boolean(item.safety_acknowledged),
    safetyDocumentVersion: item.safety_document_version || undefined,
    handoverImageUrls: item.handover_image_urls || [],
    returnImageUrls: item.return_image_urls || [],
    accessorySnapshot: item.accessory_snapshot || [],
    handoverChecklist: item.handover_checklist || [],
    returnChecklist: item.return_checklist || [],
    faultRepairId: item.fault_repair_id || undefined,
  }
}

/**
 * 预约接口。
 *
 * 关键契约：
 *  - POST /reservations             → 创建（返回新预约 id）
 *  - POST /reservations/{id}/cancel → 取消（本人，须开始前且 PENDING/APPROVED）
 *  - POST /reservations/{id}/check-in  → 兼容旧端点；现统一由负责人交接后开始使用
 *  - POST /reservations/{id}/return    → 保持 IN_USE，handover_status 进入 RETURN_PENDING 等待验收
 *  - GET  /reservations/mine        → 我的预约（分页 + 预约状态/交接状态过滤）
 *  - GET  /reservations/{id}        → 详情（本人或管理员）
 */
export const createReservation = (data: ReservationCreatePayload) =>
  request.post<unknown, ReservationCreateResultVO>('/reservations', {
    device_id: data.deviceId,
    start_date: data.startDate,
    end_date: data.endDate,
    purpose: data.purpose,
    purpose_category: data.purposeCategory,
    project_reference: data.projectReference,
    commit_mode: data.commitMode || 'all_or_nothing',
    ...(data.dates ? { dates: data.dates } : {}),
  })

export const preflightReservation = (data: ReservationCreatePayload) =>
  request.post<unknown, ReservationPreflightVO>('/reservations/preflight', {
    device_id: data.deviceId,
    start_date: data.startDate,
    end_date: data.endDate,
    purpose: data.purpose || '设备使用',
    purpose_category: data.purposeCategory || 'OTHER',
    project_reference: data.projectReference,
  })

export const cancelReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/cancel`)

export const cancelHandoverException = (id: number, reason: string) =>
  request.post<unknown, V2Reservation>(`/reservations/${id}/cancel-handover-exception`, { reason }).then(mapReservation)

/** 兼容旧的手动签到入口；实际使用仍须负责人完成交接。 */
export const checkInReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/check-in`)

export const checkOutReservation = (
  id: number,
  payload: { condition?: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string; imageUrls: string[] },
) => request.post<unknown, void>(`/reservations/${id}/return`, {
  condition: payload.condition,
  note: payload.note,
  image_urls: payload.imageUrls,
})

export interface AccessoryCheckPayload {
  name: string
  condition: 'NORMAL' | 'DAMAGED' | 'MISSING'
  note?: string
}

export const handoverReservation = (
  id: number,
  payload: { condition: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string; imageUrls: string[]; checklist: AccessoryCheckPayload[] },
) => request.post<unknown, void>(`/reservations/${id}/handover`, {
  condition: payload.condition,
  note: payload.note,
  image_urls: payload.imageUrls,
  checklist: payload.checklist,
})

export const acceptReservationReturn = (
  id: number,
  payload: { condition: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string; checklist: AccessoryCheckPayload[] },
) => request.post<unknown, void>(`/reservations/${id}/accept-return`, payload)

export const myReservations = async (q: ReservationQuery = {}): Promise<Page<ReservationVO>> => {
  const data = await request.get<unknown, V2ReservationPage>('/reservations/mine', {
    params: {
      page: q.page,
      page_size: q.size,
      status: q.status || undefined,
      handover_status: q.handoverStatus || undefined,
    },
  })
  return {
    records: data.items.map(mapReservation),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: data.pages,
    truncated: data.truncated,
  }
}

/** 按状态查询我的预约（便捷重载）。 */
export const myReservationsByStatus = (status: ReservationStatus | '', page = 1, size = 10) =>
  myReservations({ status, page, size })

export const getReservation = (id: number) =>
  request.get<unknown, V2Reservation>(`/reservations/${id}`).then(mapReservation)

export const getReservationFeedback = (id: number) =>
  request.get<unknown, ReservationFeedbackVO | null>(`/reservations/${id}/feedback`)

export const submitReservationFeedback = (
  id: number,
  payload: { rating: number; comment?: string },
) => request.post<unknown, ReservationFeedbackVO>(`/reservations/${id}/feedback`, payload)

export interface WaitlistVO {
  id: number
  deviceId: number
  deviceName?: string
  reservationDate: string
  purpose: string
  purposeCategory: ReservationVO['purposeCategory']
  projectReference?: string
  status: 'WAITING' | 'OFFERED' | 'NOTIFIED' | 'CONFIRMED' | 'EXPIRED' | 'SKIPPED' | 'CANCELLED'
  createdAt?: string
  offeredUntil?: string
}

interface V2Waitlist {
  id: number
  device_id: number
  device_name?: string | null
  reservation_date: string
  purpose: string
  purpose_category?: ReservationVO['purposeCategory']
  project_reference?: string | null
  status: WaitlistVO['status']
  created_at?: string
  offered_until?: string | null
}

function mapWaitlist(row: V2Waitlist): WaitlistVO {
  return {
    id: row.id,
    deviceId: row.device_id,
    deviceName: row.device_name || undefined,
    reservationDate: row.reservation_date,
    purpose: row.purpose,
    purposeCategory: row.purpose_category || 'OTHER',
    projectReference: row.project_reference || undefined,
    status: row.status,
    createdAt: row.created_at,
    offeredUntil: row.offered_until || undefined,
  }
}

export const joinWaitlist = async (payload: {
  deviceId: number
  reservationDate: string
  purpose: string
  purposeCategory?: ReservationVO['purposeCategory']
  projectReference?: string
}) => {
  const row = await request.post<unknown, V2Waitlist>('/reservations/waitlist', {
    device_id: payload.deviceId,
    reservation_date: payload.reservationDate,
    purpose: payload.purpose,
    purpose_category: payload.purposeCategory || 'OTHER',
    project_reference: payload.projectReference,
  })
  return mapWaitlist(row)
}

export const myWaitlist = async () => {
  const rows = await request.get<unknown, V2Waitlist[]>('/reservations/waitlist/mine')
  return rows.map(mapWaitlist)
}

export const cancelWaitlist = (id: number) =>
  request.delete<unknown, void>(`/reservations/waitlist/${id}`)

export const confirmWaitlistOffer = (id: number) =>
  request.post<unknown, { waitlist_id: number; reservation: V2Reservation }>(`/reservations/waitlist/${id}/confirm`)

export const pendingHandovers = async (
  status: 'PENDING' | 'RETURN_PENDING' | 'EXCEPTION' = 'PENDING',
  page = 1,
  size = 20,
): Promise<Page<ReservationVO>> => {
  const data = await request.get<unknown, V2ReservationPage>('/reservations/handovers', {
    params: { status, page, page_size: size },
  })
  return {
    records: data.items.map(mapReservation),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: data.pages,
    truncated: data.truncated,
  }
}
