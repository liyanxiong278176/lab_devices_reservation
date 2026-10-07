import request from './request'

export type ViolationType = 'NO_SHOW' | 'OVERDUE_RETURN' | 'MANUAL_VIOLATION'
export type AppealResult = 'MAINTAIN' | 'ADJUST' | 'REVOKE'

export interface PenaltyTier {
  occurrence: number
  points: number
  block_days: number
}

export interface PenaltyPolicy {
  college_id: number
  version: number | null
  effective_at: string | null
  grace_days: number | null
  tiers: Record<ViolationType, PenaltyTier[]>
  can_manage: boolean
  can_review: boolean
  minimum_grace_days: number
  maximum_grace_days: number
}

export interface PenaltyAppeal {
  id: number
  penalty_case_id: number
  attempt_number: number
  reason: string
  evidence: string | null
  status: string
  reviewer_id: number | null
  result: AppealResult | null
  result_reason: string | null
  submitted_at: string
  reviewed_at: string | null
  adjusted_points_delta: number | null
  adjusted_block_days: number | null
  user_name?: string
  violation_type?: ViolationType
  reservation_id?: number
  device_name?: string
  penalty_points_delta?: number
  penalty_block_days?: number
  penalty_status?: string
}

export interface PenaltyCase {
  id: number
  reservation_id: number
  user_id?: number
  user_name?: string
  violation_type: ViolationType
  reason: string
  event_at: string
  occurrence_number: number
  points_delta: number
  reservation_block_days: number
  status: string
  applied_at: string
  device_name: string
  lab_name: string | null
  appeal_count?: number
  appeals?: PenaltyAppeal[]
}

export interface PenaltyPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

export interface OverdueFollowUp {
  id: number
  operator_name: string
  contacted_at: string
  result: string
}

export interface OverdueCase {
  id: number
  reservation_id: number
  user_id: number
  user_name: string
  device_id: number
  device_name: string
  lab_id: number | null
  lab_name: string | null
  started_at: string
  grace_deadline_at: string
  status: string
  escalated_at: string | null
  escalation_reason: string | null
  followups: OverdueFollowUp[]
}

export interface GraceBounds {
  minimum_days: number
  maximum_days: number
}

export interface CollegeCreditBalance {
  college_id: number
  points: number
}

export const getPenaltyPolicy = () =>
  request.get<unknown, PenaltyPolicy>('/penalties/policy')

export const savePenaltyPolicy = (policy: {
  grace_days: number
  tiers: Record<ViolationType, PenaltyTier[]>
}) => request.put<unknown, PenaltyPolicy>('/penalties/policy', policy)

export const getGraceBounds = () =>
  request.get<unknown, GraceBounds>('/penalties/system/grace-bounds')

export const saveGraceBounds = (bounds: GraceBounds) =>
  request.put<unknown, GraceBounds>('/penalties/system/grace-bounds', bounds)

export const myPenalties = () =>
  request.get<unknown, PenaltyCase[]>('/penalties/mine')

export const myPenaltyBalance = () =>
  request.get<unknown, CollegeCreditBalance>('/penalties/balance')

export const listCollegePenalties = (page = 1, pageSize = 20) =>
  request.get<unknown, PenaltyPage<PenaltyCase>>('/penalties/cases', {
    params: { page, page_size: pageSize },
  })

export const listPenaltyAppeals = (pendingOnly = true, page = 1, pageSize = 20) =>
  request.get<unknown, PenaltyPage<PenaltyAppeal>>('/penalties/appeals', {
    params: { pending_only: pendingOnly, page, page_size: pageSize },
  })

export const submitPenaltyAppeal = (caseId: number, payload: { reason: string; evidence?: string }) =>
  request.post<unknown, PenaltyAppeal>(`/penalties/cases/${caseId}/appeals`, payload)

export const reviewPenaltyAppeal = (
  appealId: number,
  payload: {
    result: AppealResult
    result_reason: string
    points_deduction?: number
    block_days?: number
  },
) => request.post<unknown, PenaltyAppeal>(`/penalties/appeals/${appealId}/review`, payload)

export const listOverdueCases = (page = 1, pageSize = 20) =>
  request.get<unknown, PenaltyPage<OverdueCase>>('/penalties/overdue', {
    params: { page, page_size: pageSize },
  })

export const addOverdueFollowUp = (
  overdueId: number,
  payload: { result: string; contacted_at?: string },
) => request.post<unknown, OverdueFollowUp>(`/penalties/overdue/${overdueId}/followups`, payload)

export const escalateOverdue = (overdueId: number, reason: string) =>
  request.post<unknown, { id: number; status: string; escalated_at: string }>(
    `/penalties/overdue/${overdueId}/escalate`,
    { reason },
  )
