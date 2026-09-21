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

export const checkInReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/check-in`)

export const checkOutReservation = (
  id: number,
  payload: { condition?: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string } = {},
) => request.post<unknown, void>(`/reservations/${id}/return`, payload)

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
