import type { Page } from './common'

/** 设备状态枚举（与后端 DeviceStatus 一致）。 */
export type DeviceStatus = 'IDLE' | 'IN_USE' | 'MAINTENANCE'

/** 后端 DeviceVO（vo/device/DeviceVO.java）。 */
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
  pricePerHour?: number | string
  tags?: string[]
  description?: string
  createdAt?: string
  updatedAt?: string
}

/** 后端 DeviceCalendarItemVO（vo/device/DeviceCalendarItemVO.java）。 */
export interface DeviceCalendarItemVO {
  /** ISO date: yyyy-MM-dd */
  date: string
  slotIndex: number
  reservationId: number
  /** PENDING / APPROVED / IN_USE */
  status: string
}

/** 后端 DeviceCategoryNodeVO（vo/device/DeviceCategoryNodeVO.java）。 */
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
  keyword?: string
  categoryId?: number
  labId?: number
  status?: DeviceStatus | ''
  /** 0/1 */
  needApproval?: number
  minPrice?: number | string
  maxPrice?: number | string
}

export type { Page }
