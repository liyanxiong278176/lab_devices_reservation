import request from './request'
import type { Page } from '@/types/common'
import type {
  ReservationCreatePayload,
  ReservationCreateResultVO,
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
  handover_status?: string | null
  safety_required?: boolean
  safety_acknowledged?: boolean
  safety_document_version?: string | null
  reject_reason?: string | null
  inspection_condition?: 'NORMAL' | 'DAMAGED' | 'MISSING' | null
  inspection_note?: string | null
}

interface V2ReservationPage {
  items: V2Reservation[]
  total: number
  page: number
  page_size: number
  next_cursor?: number | null
  has_more?: boolean
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
  }
}

/**
 * 预约接口。
 *
 * 关键契约：
 *  - POST /reservations             → 创建（返回新预约 id）
 *  - POST /reservations/{id}/cancel → 取消（本人，须开始前且 PENDING/APPROVED）
 *  - POST /reservations/{id}/check-in  → 签到（APPROVED 且时间窗内）
 *  - POST /reservations/{id}/check-out → 归还（IN_USE → COMPLETED）
 *  - GET  /reservations/mine        → 我的预约（分页 + status 过滤）
 *  - GET  /reservations/{id}        → 详情（本人或管理员）
 */
export const createReservation = (data: ReservationCreatePayload) =>
  request.post<unknown, ReservationCreateResultVO>('/reservations', {
    device_id: data.deviceId,
    start_date: data.startDate,
    end_date: data.endDate,
    purpose: data.purpose,
    commit_mode: data.commitMode || 'all_or_nothing',
    ...(data.dates ? { dates: data.dates } : {}),
  })

export const preflightReservation = (data: ReservationCreatePayload) =>
  request.post<unknown, ReservationPreflightVO>('/reservations/preflight', {
    device_id: data.deviceId,
    start_date: data.startDate,
    end_date: data.endDate,
    purpose: data.purpose || '设备使用',
  })

export const cancelReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/cancel`)

export const checkInReservation = (id: number, qrToken?: string) =>
  request.post<unknown, void>(`/reservations/${id}/check-in`, qrToken ? { qr_token: qrToken } : {})

export const checkOutReservation = (
  id: number,
  payload: { condition?: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string; qrToken?: string } = {},
) => request.post<unknown, void>(`/reservations/${id}/return`, {
  condition: payload.condition,
  note: payload.note,
  qr_token: payload.qrToken,
})

export const handoverReservation = (
  id: number,
  payload: { condition?: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string } = {},
) => request.post<unknown, void>(`/reservations/${id}/handover`, payload)

export const acceptReservationReturn = (
  id: number,
  payload: { condition?: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string } = {},
) => request.post<unknown, void>(`/reservations/${id}/accept-return`, payload)

export const myReservations = async (q: ReservationQuery = {}): Promise<Page<ReservationVO>> => {
  const data = await request.get<unknown, V2ReservationPage>('/reservations/mine', {
    params: {
      page: q.page,
      page_size: q.size,
      cursor: q.cursor || undefined,
      status: q.status || undefined,
    },
  })
  return {
    records: data.items.map(mapReservation),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: Math.ceil(data.total / data.page_size),
    nextCursor: data.next_cursor,
    hasMore: data.has_more,
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
  status: 'WAITING' | 'NOTIFIED' | 'CANCELLED'
  createdAt?: string
}

interface V2Waitlist {
  id: number
  device_id: number
  device_name?: string | null
  reservation_date: string
  purpose: string
  status: WaitlistVO['status']
  created_at?: string
}

function mapWaitlist(row: V2Waitlist): WaitlistVO {
  return {
    id: row.id,
    deviceId: row.device_id,
    deviceName: row.device_name || undefined,
    reservationDate: row.reservation_date,
    purpose: row.purpose,
    status: row.status,
    createdAt: row.created_at,
  }
}

export const joinWaitlist = async (payload: {
  deviceId: number
  reservationDate: string
  purpose: string
}) => {
  const row = await request.post<unknown, V2Waitlist>('/reservations/waitlist', {
    device_id: payload.deviceId,
    reservation_date: payload.reservationDate,
    purpose: payload.purpose,
  })
  return mapWaitlist(row)
}

export const myWaitlist = async () => {
  const rows = await request.get<unknown, V2Waitlist[]>('/reservations/waitlist/mine')
  return rows.map(mapWaitlist)
}

export const cancelWaitlist = (id: number) =>
  request.delete<unknown, void>(`/reservations/waitlist/${id}`)

export const pendingHandovers = async (
  status: 'PENDING' | 'RETURN_PENDING' = 'PENDING',
  page = 1,
  size = 20,
  cursor?: number | null,
): Promise<Page<ReservationVO>> => {
  const data = await request.get<unknown, V2ReservationPage>('/reservations/handovers', {
    params: { status, page, page_size: size, cursor: cursor || undefined },
  })
  return {
    records: data.items.map(mapReservation),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: Math.ceil(data.total / data.page_size),
    nextCursor: data.next_cursor,
    hasMore: data.has_more,
  }
}
