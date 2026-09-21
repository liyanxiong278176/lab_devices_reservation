import type { Page } from './common'

/** 设备状态枚举（与后端 DeviceStatus 一致）。 */
export type DeviceStatus = 'IDLE' | 'IN_USE' | 'MAINTENANCE' | 'DISABLED' | 'OFFLINE' | 'RETIRED'

/** 后端设备视图。 */
export interface DeviceVO {
  id: number
  name: string
  categoryId: number | null
  categoryName?: string
  labId: number | null
  labName?: string
  brand?: string
  model?: string
  specs?: string
  imageUrl?: string
  status: DeviceStatus
  /** 0/1 — 是否需审批 */
  needApproval: number
  maxReservationHours?: number | string
  maxReservationDays?: number
  pricePerHour?: number | string
  tags?: string[]
  description?: string
  createdAt?: string
  updatedAt?: string
}

/** 后端设备日历项。 */
export interface DeviceCalendarItemVO {
  /** ISO date: yyyy-MM-dd */
  date: string
  slotIndex: number
  reservationId: number
  /** PENDING / APPROVED / IN_USE */
  status: string
}

/** 后端设备分类树节点。 */
export interface DeviceCategoryNodeVO {
  id: number
  name: string
  parentId: number
  sort?: number
  children: DeviceCategoryNodeVO[]
}

/** 设备多条件检索参数（对齐 dto/device/DeviceQueryDTO）。 */
export interface DeviceQuery {
  page?: number
  size?: number
  cursor?: number | null
  keyword?: string
  search?: string
  categoryId?: number
  labId?: number
  status?: DeviceStatus | ''
  /** 0/1 */
  needApproval?: number
  minPrice?: number | string
  maxPrice?: number | string
}

export interface DeviceAvailabilityVO {
  date: string
  available: boolean
  reservationId?: number | null
  status?: string | null
}

export type { Page }
