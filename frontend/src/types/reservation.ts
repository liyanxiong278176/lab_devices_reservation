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

export type ReservationHandoverStatus =
  | 'NOT_REQUIRED'
  | 'PENDING'
  | 'HANDED_OVER'
  | 'LEGACY_IN_USE'
  | 'EXCEPTION'
  | 'RETURN_PENDING'
  | 'RETURNED'
  | 'CANCELLED'

/** 后端自然日预约视图。 */
export interface ReservationVO {
  id: number
  userId: number
  deviceId: number
  purpose: string
  purposeCategory?: 'TEACHING' | 'RESEARCH' | 'COMPETITION_GRADUATION' | 'OTHER'
  projectReference?: string
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
  checkInAt?: string
  checkOutAt?: string
  rejectReason?: string
  inspectionCondition?: 'NORMAL' | 'DAMAGED' | 'MISSING'
  inspectionNote?: string
  deviceAssetCode?: string
  deviceLabName?: string
  requiresHandover?: boolean
  handoverStatus?: ReservationHandoverStatus
  safetyRequired?: boolean
  safetyAcknowledged?: boolean
  safetyDocumentVersion?: string
  handoverImageUrls?: string[]
  returnImageUrls?: string[]
  accessorySnapshot?: string[]
  handoverChecklist?: { name: string; condition: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string | null }[]
  returnChecklist?: { name: string; condition: 'NORMAL' | 'DAMAGED' | 'MISSING'; note?: string | null }[]
  faultRepairId?: number
}

/** 创建自然日预约参数。 */
export interface ReservationCreatePayload {
  /** Exact legacy physical device, or a resource pool for automatic allocation. */
  deviceId?: number
  poolId?: number
  /** Physical unit selected by the preflight; prevents access checks switching units. */
  preferredDeviceId?: number
  /** Number of concrete devices to bind in one all-or-nothing request. */
  quantity?: number
  startDate: string
  endDate: string
  purpose: string
  purposeCategory: 'TEACHING' | 'RESEARCH' | 'COMPETITION_GRADUATION' | 'OTHER'
  projectReference?: string
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
  requested_quantity?: number
  available_units?: number
  available_units_by_date?: {
    date: string
    available: boolean
    available_units?: number
    status?: string | null
    reason?: string | null
  }[]
  safety_required?: boolean
  safety_acknowledged?: boolean
  qualification_required?: boolean
  qualification_approved?: boolean
  safety_document_version?: string | null
  qualification_valid_until?: string | null
  same_device_suggestions?: { start_date: string; end_date: string }[]
  similar_device_suggestions?: { device_id: number; name: string; lab_name?: string | null; category_name?: string | null }[]
}

export interface ReservationCreateResultVO {
  created: ReservationVO[]
  skipped_conflicts: ReservationConflictVO[]
  batch_id?: string | null
}

/** 我的预约查询参数。 */
export interface ReservationQuery {
  status?: ReservationStatus | ''
  handoverStatus?: ReservationHandoverStatus | ''
  page?: number
  size?: number
}

export type { Page }
