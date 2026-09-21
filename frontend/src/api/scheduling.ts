import request from './request'

export interface BlackoutVO {
  id: number
  scopeType: 'COLLEGE' | 'LAB' | 'DEVICE'
  scopeId: number
  blockedDate: string
  reason: string
  active: boolean
  createdAt?: string
}

interface V2Blackout {
  id: number
  scope_type: BlackoutVO['scopeType']
  scope_id: number
  blocked_date: string
  reason: string
  active: boolean
  created_at?: string
}

function mapBlackout(row: V2Blackout): BlackoutVO {
  return {
    id: row.id,
    scopeType: row.scope_type,
    scopeId: row.scope_id,
    blockedDate: row.blocked_date,
    reason: row.reason,
    active: row.active,
    createdAt: row.created_at,
  }
}

export const listBlackouts = async (params?: { startDate?: string; endDate?: string }) => {
  const rows = await request.get<unknown, V2Blackout[]>('/blackouts', {
    params: { start_date: params?.startDate, end_date: params?.endDate },
  })
  return rows.map(mapBlackout)
}

export const createBlackout = async (payload: {
  scopeType: BlackoutVO['scopeType']
  scopeId: number
  blockedDate: string
  reason: string
}) => {
  const row = await request.post<unknown, V2Blackout>('/blackouts', {
    scope_type: payload.scopeType,
    scope_id: payload.scopeId,
    blocked_date: payload.blockedDate,
    reason: payload.reason,
  })
  return mapBlackout(row)
}

export const deleteBlackout = (id: number) => request.delete<unknown, void>(`/blackouts/${id}`)
