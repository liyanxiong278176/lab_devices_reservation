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
  assetCode?: string
  serialNumber?: string
  purchaseDate?: string
  warrantyUntil?: string
  allowExternalLoan?: boolean
  riskLevel?: 'STANDARD' | 'HIGH' | 'CRITICAL' | string
  requiresSafetyAck?: boolean
  requiresQualification?: boolean
  maxAdvanceDays?: number
  qrToken?: string
  createdAt?: string
  updatedAt?: string
}

export interface DeviceDocumentVO {
  id: number
  deviceId: number
  documentType: 'MANUAL' | 'SOP' | 'SAFETY'
  title: string
  version: string
  requiresAck: boolean
  originalName: string
  contentType: string
  sizeBytes: number
  url: string
  createdBy: number
  createdAt?: string
  publishedAt?: string
}

export interface DeviceAccessVO {
  safetyRequired: boolean
  safetyAcknowledged: boolean
  qualificationRequired: boolean
  qualificationApproved: boolean
  safetyDocumentVersion?: string | null
}

export interface QualificationVO {
  id: number
  deviceId: number
  userId: number
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | string
  qualificationType: string
  assetId?: number | null
  validUntil?: string | null
  reviewedBy?: number | null
  reviewedAt?: string | null
  note?: string | null
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
