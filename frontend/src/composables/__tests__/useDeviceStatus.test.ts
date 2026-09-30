import { describe, expect, it } from 'vitest'
import { deviceStatusTag, reservationStatusTag } from '../useDeviceStatus'

describe('status presentation mappings', () => {
  it('maps all device statuses and unknown values', () => {
    expect(deviceStatusTag('IDLE')).toBe('success')
    expect(deviceStatusTag('IN_USE')).toBe('primary')
    expect(deviceStatusTag('MAINTENANCE')).toBe('warning')
    expect(deviceStatusTag('RETIRED' as never)).toBe('info')
  })

  it('maps every reservation lifecycle status and retains unknown labels', () => {
    expect(reservationStatusTag('PENDING')).toEqual({ type: 'warning', label: '待审批' })
    expect(reservationStatusTag('APPROVED')).toEqual({ type: 'primary', label: '已通过' })
    expect(reservationStatusTag('IN_USE')).toEqual({ type: 'success', label: '使用中' })
    expect(reservationStatusTag('COMPLETED')).toEqual({ type: 'info', label: '已完成' })
    expect(reservationStatusTag('CANCELLED')).toEqual({ type: 'info', label: '已取消' })
    expect(reservationStatusTag('REJECTED')).toEqual({ type: 'danger', label: '已拒绝' })
    expect(reservationStatusTag('VIOLATED')).toEqual({ type: 'danger', label: '已违规' })
    expect(reservationStatusTag('NO_SHOW')).toEqual({ type: 'danger', label: '已爽约' })
    expect(reservationStatusTag('UNKNOWN' as never)).toEqual({ type: 'info', label: 'UNKNOWN' })
  })
})
