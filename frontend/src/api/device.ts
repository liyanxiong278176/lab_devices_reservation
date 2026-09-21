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
  description?: string | null
}

interface V2DevicePage {
  items: V2Device[]
  total: number
  page: number
  page_size: number
  next_cursor?: number | null
  has_more?: boolean
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
    description: item.description || undefined,
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
      cursor: q.cursor || undefined,
    },
  })
  return {
    records: data.items.map(mapDevice),
    total: data.total,
    size: data.page_size,
    current: data.page,
    pages: Math.ceil(data.total / data.page_size),
    nextCursor: data.next_cursor,
    hasMore: data.has_more,
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
  })

export const deleteDevice = (id: number) =>
  request.delete<unknown, void>(`/devices/${id}`)

// PATCH /devices/{id}/status?status=<s> — status 是 @RequestParam（query string）
export const patchDeviceStatus = (id: number, status: string) =>
  request.patch<unknown, void>(`/devices/${id}/status`, { status })

interface V2DeviceDocument {
  id: number
  device_id: number
  document_type: 'MANUAL' | 'SOP'
  title: string
  original_name: string
  content_type: string
  size_bytes: number
  url: string
  created_by: number
  created_at?: string
}

function mapDocument(row: V2DeviceDocument): DeviceDocumentVO {
  return {
    id: row.id,
    deviceId: row.device_id,
    documentType: row.document_type,
    title: row.title,
    originalName: row.original_name,
    contentType: row.content_type,
    sizeBytes: row.size_bytes,
    url: row.url,
    createdBy: row.created_by,
    createdAt: row.created_at,
  }
}

export const listDeviceDocuments = async (deviceId: number): Promise<DeviceDocumentVO[]> => {
  const rows = await request.get<unknown, V2DeviceDocument[]>(`/devices/${deviceId}/documents`)
  return rows.map(mapDocument)
}

export const uploadDeviceDocument = async (
  deviceId: number,
  payload: { documentType: 'MANUAL' | 'SOP'; title: string; file: File },
) => {
  const body = new FormData()
  body.append('document_type', payload.documentType)
  body.append('title', payload.title)
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
