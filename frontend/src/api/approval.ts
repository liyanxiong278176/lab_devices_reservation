import request from './request'
import type { Page } from '@/types/common'
import type { ApprovalItemVO } from '@/types/approval'

interface V2Approval {
  id: number
  user_id: number
  username?: string
  real_name?: string
  device_id: number
  device_name: string
  purpose?: string
  start_date: string
  end_date: string
  dates: string[]
  status: string
  created_at?: string
}

interface V2ApprovalPage {
  items: V2Approval[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

function mapApproval(item: V2Approval): ApprovalItemVO {
  return {
    id: item.id,
    userId: item.user_id,
    username: item.username || `user-${item.user_id}`,
    realName: item.real_name,
    deviceId: item.device_id,
    deviceName: item.device_name,
    purpose: item.purpose,
    startTime: `${item.start_date}T00:00:00`,
    endTime: `${item.end_date}T23:59:59`,
    slotCount: item.dates.length,
    status: item.status,
    createdAt: item.created_at,
  }
}

/**
 * 审批接口（对齐 ApprovalController）。全部需 reservation:approve 权限。
 *
 * 关键契约：
 *  - GET  /approvals/pending?page&size          → IPage<ApprovalItemVO>（按自辖 lab 范围过滤）
 *  - POST /approvals/{id}/approve               → 通过（PENDING→APPROVED，保留槽）
 *  - POST /approvals/{id}/reject                → 拒绝（body: { reason }，PENDING→REJECTED 释放槽）
 *  - POST /approvals/batch-approve              → 批量通过（body: { ids: [] }，任一非 PENDING 回滚整体）
 */
export const pendingApprovals = (page = 1, size = 10) =>
  request
    .get<unknown, V2ApprovalPage>('/approvals/pending', {
      params: { page, page_size: size },
    })
    .then((data): Page<ApprovalItemVO> => ({
      records: data.items.map(mapApproval),
      total: data.total,
      size: data.page_size,
      current: data.page,
      pages: data.pages,
      truncated: data.truncated,
    }))

export const approve = (id: number) =>
  request.post<unknown, void>(`/approvals/${id}/approve`, {})

// reject 用 @RequestBody RejectDTO { reason }
export const reject = (id: number, reason: string) =>
  request.post<unknown, void>(`/approvals/${id}/reject`, { reason })

// 批量通过：body BatchApproveDTO { ids: Long[] }
export const batchApprove = (ids: number[]) =>
  request.post<unknown, void>('/approvals/batch-approve', { ids })
