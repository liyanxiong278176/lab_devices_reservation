import request from './request'
import type { Page } from '@/types/common'
import type { DeviceCalendarItemVO, DeviceQuery, DeviceVO } from '@/types/device'

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
export const searchDevices = (q: DeviceQuery) =>
  request.get<unknown, Page<DeviceVO>>('/devices', { params: q })

export const getDevice = (id: number) =>
  request.get<unknown, DeviceVO>(`/devices/${id}`)

export const deviceCalendar = (id: number, from: string, to?: string) =>
  request.get<unknown, DeviceCalendarItemVO[]>(`/devices/${id}/calendar`, {
    params: { from, to },
  })

export const createDevice = (data: Record<string, unknown>) =>
  request.post<unknown, DeviceVO>('/devices', data)

// PUT /devices?id=<id> — DeviceController.update 用 @RequestParam Long id（非路径变量）
export const updateDevice = (id: number, data: Record<string, unknown>) =>
  request.put<unknown, DeviceVO>('/devices', data, { params: { id } })

export const deleteDevice = (id: number) =>
  request.delete<unknown, void>(`/devices/${id}`)

// PATCH /devices/{id}/status?status=<s> — status 是 @RequestParam（query string）
export const patchDeviceStatus = (id: number, status: string) =>
  request.patch<unknown, void>(`/devices/${id}/status`, null, { params: { status } })
