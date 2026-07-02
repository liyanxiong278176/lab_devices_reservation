import request from './request'
import type { Page } from '@/types/common'
import type { Lab } from '@/types/lab'

/**
 * 实验室接口（对齐 LabController）。
 *
 * 仅用列表分页（设备管理页下拉选项需要）。
 *  - GET /labs?page&size → IPage<Lab>（需 SYS_ADMIN/LAB_ADMIN）
 */
export const listLabs = (page = 1, size = 100) =>
  request.get<unknown, Page<Lab>>('/labs', { params: { page, size } })
