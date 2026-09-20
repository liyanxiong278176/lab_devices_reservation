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
  deviceName?: string
  startDate?: string
  endDate?: string
  dates?: string[]
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
  startDate: string
  endDate: string
  purpose: string
  commitMode?: 'all_or_nothing' | 'available_only'
  dates?: string[]
}

export interface ReservationConflictVO {
  date: string
  reason: string
  reservation_id?: number | null
  status?: string | null
}

export interface ReservationPreflightVO {
  device: import('./device').DeviceVO
  requested_dates: string[]
  available_dates: string[]
  conflicts: ReservationConflictVO[]
  all_available: boolean
}

export interface ReservationCreateResultVO {
  created: ReservationVO[]
  skipped_conflicts: ReservationConflictVO[]
  batch_id?: string | null
}

/** 我的预约查询参数（对齐 dto/reservation/ReservationQueryDTO）。 */
export interface ReservationQuery {
  status?: ReservationStatus | ''
  page?: number
  size?: number
  cursor?: number | null
}

export type { Page }
