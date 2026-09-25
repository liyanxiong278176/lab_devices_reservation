import request from './request'
import type { Page } from '@/types/common'
import type {
  DeviceAvailabilityVO,
  DeviceCalendarItemVO,
  DeviceDocumentVO,
  DeviceQuery,
  DeviceVO,
} from '@/types/device'

interface V2Device {
  id: number
  name: string
  status: DeviceVO['status']
  brand?: string
  model?: string
  specs?: string
  image_url?: string
  category_id?: number | null
  category_name?: string | null
  lab_id?: number | null
  lab_name?: string | null
  need_approval: boolean
  max_reservation_days: number
  tags?: string[] | null
  accessory_checklist?: string[] | null
  description?: string | null
  asset_code?: string | null
  serial_number?: string | null
  purchase_date?: string | null
  warranty_until?: string | null
  allow_external_loan?: boolean
  risk_level?: string
  requires_safety_ack?: boolean
  requires_qualification?: boolean
  max_advance_days?: number | null
}

interface V2DevicePage {
  items: V2Device[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

interface V2DeviceAvailability {
  date: string
  available: boolean
  reservation_id?: number | null
  status?: string | null
}

function mapDevice(item: V2Device): DeviceVO {
  return {
    id: item.id,
    name: item.name,
    categoryId: item.category_id ?? null,
    categoryName: item.category_name || undefined,
    labId: item.lab_id ?? null,
    labName: item.lab_name || undefined,
    brand: item.brand,
    model: item.model,
    specs: item.specs,
    imageUrl: item.image_url,
    status: item.status,
    needApproval: item.need_approval ? 1 : 0,
    maxReservationDays: item.max_reservation_days,
    maxReservationHours: item.max_reservation_days * 24,
    tags: item.tags || undefined,
    accessoryChecklist: item.accessory_checklist || [],
    description: item.description || undefined,
    assetCode: item.asset_code || undefined,
    serialNumber: item.serial_number || undefined,
    purchaseDate: item.purchase_date || undefined,
    warrantyUntil: item.warranty_until || undefined,
    allowExternalLoan: Boolean(item.allow_external_loan),
    riskLevel: item.risk_level || 'STANDARD',
    requiresSafetyAck: Boolean(item.requires_safety_ack),
    requiresQualification: Boolean(item.requires_qualification),
    maxAdvanceDays: item.max_advance_days ?? undefined,
  }
}

/**
 * 设备接口（对齐 DeviceController）。
 *
 * 关键契约：
 *  - GET    /devices                → 多条件检索，返回 IPage<DeviceVO>
 *  - GET    /devices/{id}           → 设备详情
 *  - GET    /devices/{id}/calendar  → 日历（占用 slot 列表），from/to 为 ISO 日期
 *  - POST   /devices                → 新建（需 device:manage 权限）
 *  - PUT    /devices?id=<id>        → 更新（注意：id 是 @RequestParam，非路径变量！）
 *  - DELETE /devices/{id}           → 删除
 *  - PATCH  /devices/{id}/status?status=<s>  → 改状态（status 是 @RequestParam）
 */
export const searchDevices = async (q: DeviceQuery): Promise<Page<DeviceVO>> => {
  const data = await request.get<unknown, V2DevicePage>('/devices', {
    params: {
      page: q.page,
      page_size: q.size,
      search: q.keyword || q.search,
      lab_id: q.labId,
      status: q.status || undefined,
    },
  })
  return {
    records: data.items.map(mapDevice),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: data.pages,
    truncated: data.truncated,
  }
}

export const getDevice = async (id: number): Promise<DeviceVO> => {
  const data = await request.get<unknown, V2Device>(`/devices/${id}`)
  return mapDevice(data)
}

export const deviceCalendar = async (id: number, from: string, to?: string) => {
  const days = await deviceAvailability(id, from, to)
  return days
    .filter((day) => !day.available)
    .map(
      (day): DeviceCalendarItemVO => ({
        date: day.date,
        slotIndex: 0,
        reservationId: day.reservationId || 0,
        status: day.status || 'BLOCKED',
      }),
    )
}

export const deviceAvailability = async (
  id: number,
  from: string,
  to?: string,
): Promise<DeviceAvailabilityVO[]> => {
  const days = await request.get<unknown, V2DeviceAvailability[]>(
    `/devices/${id}/availability`,
    { params: { start_date: from, end_date: to || from } },
  )
  return days.map((day) => ({
    date: day.date,
    available: day.available,
    reservationId: day.reservation_id ?? null,
    status: day.status ?? null,
  }))
}

export const createDevice = (data: Record<string, unknown>) =>
  request.post<unknown, DeviceVO>('/devices', {
    name: data.name,
    lab_id: data.labId,
    category_id: data.categoryId,
    brand: data.brand,
    model: data.model,
    specs: data.specs,
    image_url: data.imageUrl,
    description: data.description,
    need_approval: Boolean(data.needApproval),
    max_reservation_days: data.maxReservationDays || 8,
    tags: data.tags,
    accessory_checklist: data.accessoryChecklist,
    asset_code: data.assetCode,
    serial_number: data.serialNumber,
    purchase_date: data.purchaseDate,
    warranty_until: data.warrantyUntil,
    allow_external_loan: Boolean(data.allowExternalLoan),
    risk_level: data.riskLevel || 'STANDARD',
    requires_safety_ack: Boolean(data.requiresSafetyAck),
    requires_qualification: Boolean(data.requiresQualification),
    max_advance_days: data.maxAdvanceDays,
  })

export const updateDevice = (id: number, data: Record<string, unknown>) =>
  request.put<unknown, DeviceVO>(`/devices/${id}`, {
    name: data.name,
    lab_id: data.labId,
    category_id: data.categoryId,
    brand: data.brand,
    model: data.model,
    specs: data.specs,
    image_url: data.imageUrl,
    description: data.description,
    need_approval: Boolean(data.needApproval),
    max_reservation_days: data.maxReservationDays || 8,
    tags: data.tags,
    accessory_checklist: data.accessoryChecklist,
    asset_code: data.assetCode,
    serial_number: data.serialNumber,
    purchase_date: data.purchaseDate,
    warranty_until: data.warrantyUntil,
    allow_external_loan: Boolean(data.allowExternalLoan),
    risk_level: data.riskLevel || 'STANDARD',
    requires_safety_ack: Boolean(data.requiresSafetyAck),
    requires_qualification: Boolean(data.requiresQualification),
    max_advance_days: data.maxAdvanceDays,
  })

export const deleteDevice = (id: number) =>
  request.delete<unknown, void>(`/devices/${id}`)

// PATCH /devices/{id}/status?status=<s> — status 是 @RequestParam（query string）
export const patchDeviceStatus = (id: number, status: string) =>
  request.patch<unknown, void>(`/devices/${id}/status`, { status })

interface V2DeviceDocument {
  id: number
  device_id: number
  document_type: 'MANUAL' | 'SOP' | 'SAFETY'
  title: string
  version: string
  requires_ack: boolean
  original_name: string
  content_type: string
  size_bytes: number
  url: string
  created_by: number
  created_at?: string
  published_at?: string | null
}

function mapDocument(row: V2DeviceDocument): DeviceDocumentVO {
  return {
    id: row.id,
    deviceId: row.device_id,
    documentType: row.document_type,
    title: row.title,
    version: row.version || '1.0',
    requiresAck: Boolean(row.requires_ack),
    originalName: row.original_name,
    contentType: row.content_type,
    sizeBytes: row.size_bytes,
    url: row.url,
    createdBy: row.created_by,
    createdAt: row.created_at,
    publishedAt: row.published_at || undefined,
  }
}

export const listDeviceDocuments = async (deviceId: number): Promise<DeviceDocumentVO[]> => {
  const rows = await request.get<unknown, V2DeviceDocument[]>(`/devices/${deviceId}/documents`)
  return rows.map(mapDocument)
}

export const uploadDeviceDocument = async (
  deviceId: number,
  payload: {
    documentType: 'MANUAL' | 'SOP' | 'SAFETY'
    title: string
    version?: string
    requiresAck?: boolean
    file: File
  },
) => {
  const body = new FormData()
  body.append('document_type', payload.documentType)
  body.append('title', payload.title)
  body.append('version', payload.version || '1.0')
  body.append('requires_ack', String(Boolean(payload.requiresAck)))
  body.append('file', payload.file)
  const row = await request.post<unknown, V2DeviceDocument>(`/devices/${deviceId}/documents`, body)
  return mapDocument(row)
}

export const archiveDeviceDocument = (deviceId: number, documentId: number) =>
  request.delete<unknown, void>(`/devices/${deviceId}/documents/${documentId}`)

export const downloadDeviceDocument = async (document: DeviceDocumentVO) => {
  const blob = await request.get<Blob, Blob>(document.url, { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement('a')
  anchor.href = url
  anchor.download = document.originalName
  anchor.click()
  URL.revokeObjectURL(url)
}

interface V2DeviceAccess {
  safety_required: boolean
  safety_acknowledged: boolean
  qualification_required: boolean
  qualification_approved: boolean
  safety_document_version?: string | null
}

interface V2Qualification {
  id: number
  device_id: number
  user_id: number
  status: string
  qualification_type: string
  asset_id?: number | null
  valid_until?: string | null
  reviewed_by?: number | null
  reviewed_at?: string | null
  note?: string | null
  created_at?: string
  updated_at?: string
}

function mapAccess(row: V2DeviceAccess) {
  return {
    safetyRequired: Boolean(row.safety_required),
    safetyAcknowledged: Boolean(row.safety_acknowledged),
    qualificationRequired: Boolean(row.qualification_required),
    qualificationApproved: Boolean(row.qualification_approved),
    safetyDocumentVersion: row.safety_document_version || undefined,
  }
}

function mapQualification(row: V2Qualification) {
  return {
    id: row.id,
    deviceId: row.device_id,
    userId: row.user_id,
    status: row.status,
    qualificationType: row.qualification_type,
    assetId: row.asset_id ?? null,
    validUntil: row.valid_until ?? null,
    reviewedBy: row.reviewed_by ?? null,
    reviewedAt: row.reviewed_at ?? null,
    note: row.note ?? null,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

export const listSafetyDocuments = (deviceId: number) =>
  request.get<unknown, V2DeviceDocument[]>(`/devices/${deviceId}/safety-documents`).then((rows) => rows.map(mapDocument))

export const getDeviceAccess = (deviceId: number) =>
  request.get<unknown, V2DeviceAccess>(`/devices/${deviceId}/access`).then(mapAccess)

export const acknowledgeSafety = (deviceId: number, reservationId?: number) =>
  request.post<unknown, { device_id: number; acknowledged: boolean; version: string }>(
    `/devices/${deviceId}/safety-ack`,
    reservationId ? { reservation_id: reservationId } : {},
  )

export const uploadQualificationMaterial = async (deviceId: number, file: File) => {
  const body = new FormData()
  body.append('file', file)
  return request.post<unknown, { asset_id: number; url: string; name: string }>(
    `/devices/${deviceId}/qualification-uploads`,
    body,
  )
}

export const submitQualification = (
  deviceId: number,
  payload: { qualificationType?: string; assetId?: number | null; note?: string },
) =>
  request
    .post<unknown, V2Qualification>(`/devices/${deviceId}/qualifications`, {
      qualification_type: payload.qualificationType || 'TRAINING',
      asset_id: payload.assetId ?? undefined,
      note: payload.note,
    })
    .then(mapQualification)

export const myQualification = (deviceId: number) =>
  request
    .get<unknown, V2Qualification | null>(`/devices/${deviceId}/qualifications/mine`)
    .then((row) => (row ? mapQualification(row) : null))

export const listQualifications = (deviceId: number) =>
  request.get<unknown, V2Qualification[]>(`/devices/${deviceId}/qualifications`).then((rows) => rows.map(mapQualification))

export const reviewQualification = (
  deviceId: number,
  qualificationId: number,
  payload: { status: 'APPROVED' | 'REJECTED'; validUntil?: string; note?: string },
) =>
  request
    .patch<unknown, V2Qualification>(`/devices/${deviceId}/qualifications/${qualificationId}`, {
      status: payload.status,
      valid_until: payload.validUntil,
      note: payload.note,
    })
    .then(mapQualification)
