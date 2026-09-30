import { describe, expect, it } from 'vitest'
import {
  BG_SURFACE, BLUE, BODY, DEVICE_STATUS_COLORS, DEVICE_STATUS_LABELS, DEVICE_STATUS_ORDER,
  ERROR, HAIRLINE, INK, MUTED, ORANGE, REPAIR_STATUS_COLORS, REPAIR_STATUS_LABELS,
  REPAIR_STATUS_ORDER, RESERVATION_STATUS_COLORS, RESERVATION_STATUS_LABELS,
  RESERVATION_STATUS_ORDER, SERIES_PALETTE, SUCCESS, SURFACE_SOFT, VIOLET, WARNING, toStatusData,
} from '../palette'

describe('chart palette and status conversion', () => {
  it('exports the semantic palette and stable status orders', () => {
    expect([INK, BLUE, SUCCESS, WARNING, ERROR, VIOLET, ORANGE, MUTED, BODY, HAIRLINE, SURFACE_SOFT, BG_SURFACE])
      .toHaveLength(12)
    expect(SERIES_PALETTE).toEqual([INK, BLUE, SUCCESS, WARNING, ERROR, VIOLET])
    expect(DEVICE_STATUS_ORDER).toEqual(['IDLE', 'IN_USE', 'MAINTENANCE'])
    expect(REPAIR_STATUS_ORDER).toEqual(['PENDING', 'PROCESSING', 'RESOLVED', 'REJECTED'])
    expect(RESERVATION_STATUS_ORDER).toContain('NO_SHOW')
    expect(DEVICE_STATUS_LABELS.IDLE).toBe('空闲')
    expect(REPAIR_STATUS_LABELS.PROCESSING).toBe('处理中')
    expect(RESERVATION_STATUS_LABELS.NO_SHOW).toBe('爽约')
    expect(DEVICE_STATUS_COLORS.IDLE).toBe(SUCCESS)
    expect(REPAIR_STATUS_COLORS.REJECTED).toBe(ERROR)
    expect(RESERVATION_STATUS_COLORS.NO_SHOW).toBe(ORANGE)
  })

  it('returns empty data for missing maps and filters, orders and colors present statuses', () => {
    expect(toStatusData(undefined, ['A'], {}, {})).toEqual([])
    expect(toStatusData(null, ['A'], {}, {})).toEqual([])
    expect(toStatusData({ B: 4, A: 0, C: 2 }, ['A', 'B', 'C'], { B: 'Bee' }, { B: BLUE, C: SUCCESS }))
      .toEqual([
        { name: 'Bee', value: 4, color: BLUE },
        { name: 'C', value: 2, color: SUCCESS },
      ])
  })
})
