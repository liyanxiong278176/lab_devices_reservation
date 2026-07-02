import request from './request'
import type { DeviceCategoryNodeVO } from '@/types/device'

/**
 * 设备分类接口（对齐 DeviceCategoryController）。
 *
 * 唯一接口：GET /device-categories → 分类树
 */
export const categoryTree = () =>
  request.get<unknown, DeviceCategoryNodeVO[]>('/device-categories')
