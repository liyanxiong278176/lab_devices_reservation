import type { ReservationCreatePayload } from '@/types/reservation'

export interface PendingReservationRequest {
  userId: number
  token: string
  payload: ReservationCreatePayload
  createdAt: string
}

const PREFIX = 'lab-reservation-pending:v1'

export function reservationPendingPointerKey(userId: number): string {
  return `${PREFIX}:${userId}:current`
}

function reservationPendingRecordKey(userId: number, token: string): string {
  return `${PREFIX}:${userId}:${encodeURIComponent(token)}`
}

export function readPendingReservationRequest(
  userId: number,
): PendingReservationRequest | null {
  if (typeof window === 'undefined') return null
  try {
    const token = window.localStorage.getItem(reservationPendingPointerKey(userId))
    if (!token) return null
    const raw = window.localStorage.getItem(reservationPendingRecordKey(userId, token))
    if (!raw) {
      window.localStorage.removeItem(reservationPendingPointerKey(userId))
      return null
    }
    const value = JSON.parse(raw) as PendingReservationRequest
    if (value.userId !== userId || value.token !== token || !value.payload) return null
    return value
  } catch {
    return null
  }
}

export function savePendingReservationRequest(
  request: PendingReservationRequest,
): void {
  if (typeof window === 'undefined') return
  const recordKey = reservationPendingRecordKey(request.userId, request.token)
  const pointerKey = reservationPendingPointerKey(request.userId)
  window.localStorage.setItem(recordKey, JSON.stringify(request))
  window.localStorage.setItem(pointerKey, request.token)
}

export function clearPendingReservationRequest(
  userId: number,
  token?: string,
): void {
  if (typeof window === 'undefined') return
  try {
    const pointerKey = reservationPendingPointerKey(userId)
    const currentToken = window.localStorage.getItem(pointerKey)
    const tokenToRemove = token || currentToken
    if (currentToken && (!token || currentToken === token)) {
      window.localStorage.removeItem(pointerKey)
    }
    if (tokenToRemove) {
      window.localStorage.removeItem(reservationPendingRecordKey(userId, tokenToRemove))
    }
  } catch {
    // Storage can be unavailable; MySQL idempotency remains authoritative.
  }
}
