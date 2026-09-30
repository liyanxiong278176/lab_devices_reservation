import request from './request'

export type ReservationRuleScope = 'GLOBAL' | 'COLLEGE' | 'LAB' | 'DEVICE'
export type ReservationRuleCategory = 'ALL' | 'STUDENT' | 'LAB_ADMIN'

export interface ReservationRuleVO {
  id: number
  scopeType: ReservationRuleScope
  scopeId: number
  scopeName: string
  userCategory: ReservationRuleCategory
  maxBookingDays: number | null
  maxAdvanceDays: number | null
  approvalRequired: boolean | null
}

export interface ReservationRulePageVO {
  items: ReservationRuleVO[]
  total: number
  page: number
  pageSize: number
  pages: number
  truncated: boolean
}

interface V2ReservationRule {
  id: number
  scope_type: ReservationRuleScope
  scope_id: number
  scope_name: string
  user_category: ReservationRuleCategory
  max_booking_days: number | null
  max_advance_days: number | null
  approval_required: boolean | null
}

interface V2ReservationRulePage {
  items: V2ReservationRule[]
  total: number
  page: number
  page_size: number
  pages: number
  truncated: boolean
}

export interface ReservationRulePayload {
  scopeType: ReservationRuleScope
  scopeId: number
  userCategory: ReservationRuleCategory
  maxBookingDays: number | null
  maxAdvanceDays: number | null
  approvalRequired: boolean | null
}

const mapRule = (row: V2ReservationRule): ReservationRuleVO => ({
  id: row.id,
  scopeType: row.scope_type,
  scopeId: row.scope_id,
  scopeName: row.scope_name,
  userCategory: row.user_category,
  maxBookingDays: row.max_booking_days,
  maxAdvanceDays: row.max_advance_days,
  approvalRequired: row.approval_required,
})

export const listReservationRules = async (
  page = 1,
  pageSize = 20,
  filters: {
    scopeType?: ReservationRuleScope
    userCategory?: ReservationRuleCategory
    scopeId?: number
  } = {},
): Promise<ReservationRulePageVO> => {
  const result = await request.get<unknown, V2ReservationRulePage>('/reservation-rules', {
    params: {
      page,
      page_size: pageSize,
      scope_type: filters.scopeType,
      user_category: filters.userCategory,
      scope_id: filters.scopeId,
    },
  })
  return {
    items: result.items.map(mapRule),
    total: result.total,
    page: result.page,
    pageSize: result.page_size,
    pages: result.pages,
    truncated: result.truncated,
  }
}

export const saveReservationRule = async (payload: ReservationRulePayload) => {
  const row = await request.put<unknown, V2ReservationRule>('/reservation-rules', {
    scope_type: payload.scopeType,
    scope_id: payload.scopeId,
    user_category: payload.userCategory,
    max_booking_days: payload.maxBookingDays,
    max_advance_days: payload.maxAdvanceDays,
    approval_required: payload.approvalRequired,
  })
  return mapRule(row)
}

export const deleteReservationRule = (id: number) =>
  request.delete<unknown, void>(`/reservation-rules/${id}`)
