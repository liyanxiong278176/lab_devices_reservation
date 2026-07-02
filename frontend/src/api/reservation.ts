import request from './request'
import type { Page } from '@/types/common'
import type {
  ReservationCreatePayload,
  ReservationQuery,
  ReservationStatus,
  ReservationVO,
} from '@/types/reservation'

/**
 * 预约接口（对齐 ReservationController）。
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
  request.post<unknown, number>('/reservations', data)

export const cancelReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/cancel`)

export const checkInReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/check-in`)

export const checkOutReservation = (id: number) =>
  request.post<unknown, void>(`/reservations/${id}/check-out`)

export const myReservations = (q: ReservationQuery = {}) =>
  request.get<unknown, Page<ReservationVO>>('/reservations/mine', { params: q })

/** 按状态查询我的预约（便捷重载）。 */
export const myReservationsByStatus = (status: ReservationStatus | '', page = 1, size = 10) =>
  myReservations({ status, page, size })

export const getReservation = (id: number) =>
  request.get<unknown, ReservationVO>(`/reservations/${id}`)
