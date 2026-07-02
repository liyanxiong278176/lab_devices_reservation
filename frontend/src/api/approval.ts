import request from './request'
import type { Page } from '@/types/common'
import type { ApprovalItemVO } from '@/types/approval'

/**
 * 审批接口（对齐 ApprovalController）。全部需 device:approve 权限。
 *
 * 关键契约：
 *  - GET  /approvals/pending?page&size          → IPage<ApprovalItemVO>（按自辖 lab 范围过滤）
 *  - POST /approvals/{id}/approve               → 通过（PENDING→APPROVED，保留槽）
 *  - POST /approvals/{id}/reject                → 拒绝（body: { reason }，PENDING→REJECTED 释放槽）
 *  - POST /approvals/batch-approve              → 批量通过（body: { ids: [] }，任一非 PENDING 回滚整体）
 */
export const pendingApprovals = (page = 1, size = 10) =>
  request.get<unknown, Page<ApprovalItemVO>>('/approvals/pending', { params: { page, size } })

export const approve = (id: number) =>
  request.post<unknown, void>(`/approvals/${id}/approve`)

// reject 用 @RequestBody RejectDTO { reason }
export const reject = (id: number, reason: string) =>
  request.post<unknown, void>(`/approvals/${id}/reject`, { reason })

// 批量通过：body BatchApproveDTO { ids: Long[] }
export const batchApprove = (ids: number[]) =>
  request.post<unknown, void>('/approvals/batch-approve', { ids })
