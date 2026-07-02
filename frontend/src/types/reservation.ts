import type { Page } from './common'

/** 预约状态枚举（与后端 ReservationStatus 一致）。 */
export type ReservationStatus =
  | 'PENDING'
  | 'APPROVED'
  | 'IN_USE'
  | 'COMPLETED'
  | 'CANCELLED'
  | 'REJECTED'
  | 'VIOLATED'
  | 'NO_SHOW'

/** 后端 ReservationVO（vo/reservation/ReservationVO.java）。 */
export interface ReservationVO {
  id: number
  userId: number
  deviceId: number
  purpose: string
  /** ISO LocalDateTime: yyyy-MM-ddTHH:mm:ss */
  startTime: string
  endTime: string
  slotCount: number
  status: ReservationStatus
  createdAt?: string
}

/** 创建预约参数（对齐 dto/reservation/ReservationCreateDTO）。 */
export interface ReservationCreatePayload {
  deviceId: number
  /** ISO LocalDateTime */
  startTime: string
  /** ISO LocalDateTime */
  endTime: string
  purpose: string
}

/** 我的预约查询参数（对齐 dto/reservation/ReservationQueryDTO）。 */
export interface ReservationQuery {
  status?: ReservationStatus | ''
  page?: number
  size?: number
}

export type { Page }
