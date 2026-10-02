import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('../request', () => ({ default: http }))

import * as notificationApi from '../notification'
import * as recommendationApi from '../recommendation'
import * as repairApi from '../repair'
import * as reservationApi from '../reservation'

describe('reservation and user-facing API contracts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    http.get.mockResolvedValue(undefined)
    http.post.mockResolvedValue(undefined)
    http.patch.mockResolvedValue(undefined)
    http.put.mockResolvedValue(undefined)
    http.delete.mockResolvedValue(undefined)
  })

  it('sends resource-pool allocation and the retry-safe idempotency key', async () => {
    await reservationApi.createReservation({
      poolId: 17,
      preferredDeviceId: 42,
      startDate: '2026-10-01',
      endDate: '2026-10-02',
      purpose: 'pool booking',
      purposeCategory: 'RESEARCH',
    }, 'retry-key-1')

    expect(http.post).toHaveBeenCalledWith('/reservations', {
      pool_id: 17,
      preferred_device_id: 42,
      start_date: '2026-10-01',
      end_date: '2026-10-02',
      purpose: 'pool booking',
      purpose_category: 'RESEARCH',
      project_reference: undefined,
      commit_mode: 'all_or_nothing',
    }, { headers: { 'Idempotency-Key': 'retry-key-1' } })
  })

  it('serializes create/preflight defaults and reservation handover actions', async () => {
    await reservationApi.createReservation({
      deviceId: 8, startDate: '2026-09-30', endDate: '2026-10-01', purpose: 'study',
      purposeCategory: 'RESEARCH', projectReference: 'P-1', commitMode: 'available_only', dates: ['2026-09-30'],
    })
    await reservationApi.createReservation({
      deviceId: 9, startDate: '2026-10-02', endDate: '2026-10-02', purpose: 'class', purposeCategory: 'OTHER',
    })
    await reservationApi.preflightReservation({
      deviceId: 9, startDate: '2026-10-02', endDate: '2026-10-02', purpose: '', purposeCategory: '' as never,
    })
    await reservationApi.preflightReservation({
      deviceId: 8, startDate: '2026-10-03', endDate: '2026-10-03', purpose: 'experiment',
      purposeCategory: 'RESEARCH', projectReference: 'P-2',
    })
    expect(http.post.mock.calls.slice(0, 4)).toEqual([
      ['/reservations', {
        device_id: 8, start_date: '2026-09-30', end_date: '2026-10-01', purpose: 'study',
        purpose_category: 'RESEARCH', project_reference: 'P-1', commit_mode: 'available_only', dates: ['2026-09-30'],
      }],
      ['/reservations', {
        device_id: 9, start_date: '2026-10-02', end_date: '2026-10-02', purpose: 'class',
        purpose_category: 'OTHER', project_reference: undefined, commit_mode: 'all_or_nothing',
      }],
      ['/reservations/preflight', {
        device_id: 9, start_date: '2026-10-02', end_date: '2026-10-02',
        purpose: '设备使用', purpose_category: 'OTHER', project_reference: undefined,
      }],
      ['/reservations/preflight', {
        device_id: 8, start_date: '2026-10-03', end_date: '2026-10-03',
        purpose: 'experiment', purpose_category: 'RESEARCH', project_reference: 'P-2',
      }],
    ])

    await reservationApi.cancelReservation(1)
    http.post.mockResolvedValueOnce({
      id: 2, device_id: 3, device_name: 'scope', user_id: 4, start_date: '2026-10-01',
      end_date: '2026-10-01', dates: ['2026-10-01'], status: 'CANCELLED', need_approval: false,
    })
    await expect(reservationApi.cancelHandoverException(2, 'broken')).resolves.toMatchObject({
      id: 2, purpose: '', purposeCategory: 'OTHER', handoverStatus: 'NOT_REQUIRED',
      requiresHandover: false, faultRepairId: undefined,
    })
    await reservationApi.checkInReservation(3)
    await reservationApi.checkOutReservation(4, { condition: 'DAMAGED', note: 'scratch', imageUrls: ['/return.png'] })
    const checklist = [{ name: 'power', condition: 'NORMAL' as const }]
    await reservationApi.handoverReservation(5, {
      condition: 'NORMAL', note: 'issued', imageUrls: ['/out.png'], checklist,
    })
    await reservationApi.acceptReservationReturn(6, { condition: 'NORMAL', note: 'ok', checklist })
    expect(http.post.mock.calls.slice(4)).toEqual([
      ['/reservations/1/cancel'],
      ['/reservations/2/cancel-handover-exception', { reason: 'broken' }],
      ['/reservations/3/check-in'],
      ['/reservations/4/return', { condition: 'DAMAGED', note: 'scratch', image_urls: ['/return.png'] }],
      ['/reservations/5/handover', {
        condition: 'NORMAL', note: 'issued', image_urls: ['/out.png'], checklist,
      }],
      ['/reservations/6/accept-return', { condition: 'NORMAL', note: 'ok', checklist }],
    ])
  })

  it('maps reservation optionals for both present and empty server values', async () => {
    const base = {
      id: 1, device_id: 2, device_name: 'scope', user_id: 3,
      start_date: '2026-09-30', end_date: '2026-10-01', dates: ['a', 'b'],
      status: 'APPROVED' as const, need_approval: true,
    }
    const rich = {
      ...base, purpose: 'lab', purpose_category: 'RESEARCH', project_reference: 'P-8',
      created_at: 'created', check_in_at: 'in', check_out_at: 'out', batch_id: 'batch',
      device_asset_code: 'asset', device_lab_name: 'lab', requires_handover: true,
      handover_status: 'RETURN_PENDING', safety_required: true, safety_acknowledged: true,
      safety_document_version: 'v3', reject_reason: 'reason', inspection_condition: 'DAMAGED',
      inspection_note: 'note', handover_image_urls: ['/h.png'], return_image_urls: ['/r.png'],
      accessory_snapshot: ['power'], handover_checklist: [{ name: 'power' }],
      return_checklist: [{ name: 'power' }], fault_repair_id: 9,
    }
    const empty = {
      ...base, id: 2, purpose: '', purpose_category: '', project_reference: null,
      check_in_at: null, check_out_at: null, reject_reason: null, inspection_condition: null,
      inspection_note: null, device_asset_code: null, device_lab_name: null, requires_handover: false,
      handover_status: null, safety_required: false, safety_acknowledged: false,
      safety_document_version: null, handover_image_urls: undefined, return_image_urls: undefined,
      accessory_snapshot: undefined, handover_checklist: undefined, return_checklist: undefined,
      fault_repair_id: null,
    }
    http.get.mockResolvedValueOnce({
      items: [rich, empty], total: 2, page: 1, page_size: 10, pages: 1, truncated: false,
    }).mockResolvedValueOnce(rich).mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 10, pages: 0, truncated: false })
      .mockResolvedValueOnce({ items: [], total: 0, page: 2, page_size: 4, pages: 0, truncated: false })
      .mockResolvedValueOnce({ items: [], total: 0, page: 3, page_size: 5, pages: 0, truncated: false })
    await expect(reservationApi.myReservations({
      page: 1, size: 10, status: 'APPROVED', handoverStatus: 'RETURN_PENDING',
    })).resolves.toMatchObject({
      records: [
        expect.objectContaining({
          purpose: 'lab', purposeCategory: 'RESEARCH', projectReference: 'P-8', slotCount: 2,
          startTime: '2026-09-30T00:00:00', endTime: '2026-10-01T23:59:59',
          handoverStatus: 'RETURN_PENDING', handoverImageUrls: ['/h.png'], faultRepairId: 9,
        }),
        expect.objectContaining({
          purpose: '', purposeCategory: 'OTHER', projectReference: undefined, slotCount: 2,
          requiresHandover: false, handoverStatus: 'NOT_REQUIRED', safetyRequired: false,
          handoverImageUrls: [], returnImageUrls: [], handoverChecklist: [], returnChecklist: [],
        }),
      ],
      total: 2, size: 10, current: 1, pages: 1, truncated: false,
    })
    expect(http.get).toHaveBeenNthCalledWith(1, '/reservations/mine', {
      params: { page: 1, page_size: 10, status: 'APPROVED', handover_status: 'RETURN_PENDING' },
    })
    await expect(reservationApi.getReservation(1)).resolves.toMatchObject({ id: 1, userId: 3 })
    await expect(reservationApi.getReservationFeedback(1)).resolves.toBeNull()
    await reservationApi.submitReservationFeedback(1, { rating: 5, comment: 'good' })
    await reservationApi.myReservations()
    await reservationApi.myReservationsByStatus('', 2, 4)
    await reservationApi.pendingHandovers('EXCEPTION', 3, 5)
    expect(http.get).toHaveBeenNthCalledWith(4, '/reservations/mine', {
      params: { page: undefined, page_size: undefined, status: undefined, handover_status: undefined },
    })
    expect(http.get).toHaveBeenNthCalledWith(5, '/reservations/mine', {
      params: { page: 2, page_size: 4, status: undefined, handover_status: undefined },
    })
    expect(http.get).toHaveBeenNthCalledWith(6, '/reservations/handovers', {
      params: { status: 'EXCEPTION', page: 3, page_size: 5 },
    })
    expect(http.post).toHaveBeenLastCalledWith('/reservations/1/feedback', { rating: 5, comment: 'good' })
  })

  it('maps waitlist defaults and covers all waitlist actions', async () => {
    http.post.mockResolvedValueOnce({
      id: 10, device_id: 2, device_name: null, reservation_date: '2026-10-02', purpose: 'lab',
      status: 'WAITING', created_at: 'today', offered_until: null,
    })
    await expect(reservationApi.joinWaitlist({
      deviceId: 2, reservationDate: '2026-10-02', purpose: 'lab',
    })).resolves.toEqual({
      id: 10, deviceId: 2, deviceName: undefined, reservationDate: '2026-10-02', purpose: 'lab',
      purposeCategory: 'OTHER', projectReference: undefined, status: 'WAITING',
      createdAt: 'today', offeredUntil: undefined,
    })
    http.get.mockResolvedValueOnce([{
      id: 11, device_id: 3, device_name: 'scope', reservation_date: '2026-10-03', purpose: 'class',
      purpose_category: 'COURSE', project_reference: 'C-1', status: 'OFFERED', offered_until: 'soon',
    }])
    await expect(reservationApi.myWaitlist()).resolves.toMatchObject([{
      id: 11, deviceId: 3, deviceName: 'scope', purposeCategory: 'COURSE',
      projectReference: 'C-1', status: 'OFFERED', offeredUntil: 'soon',
    }])
    await reservationApi.cancelWaitlist(10)
    await reservationApi.confirmWaitlistOffer(11)
    expect(http.post).toHaveBeenCalledWith('/reservations/waitlist', {
      device_id: 2, reservation_date: '2026-10-02', purpose: 'lab',
      purpose_category: 'OTHER', project_reference: undefined,
    })
    expect(http.get).toHaveBeenCalledWith('/reservations/waitlist/mine')
    expect(http.delete).toHaveBeenCalledWith('/reservations/waitlist/10')
    expect(http.post).toHaveBeenLastCalledWith('/reservations/waitlist/11/confirm')
  })

  it('maps notification pages and submits read operations', async () => {
    const page = { records: [{ id: 1 }], total: 5, size: 10, current: 2, pages: 1, truncated: true }
    http.get.mockResolvedValueOnce(page).mockResolvedValueOnce({ total: 7 }).mockResolvedValueOnce(page)
    await expect(notificationApi.myNotifications({ onlyUnread: true, page: 2, size: 10 })).resolves.toEqual(page)
    await expect(notificationApi.unreadCount()).resolves.toBe(7)
    await notificationApi.myNotifications()
    await notificationApi.markRead(4)
    await notificationApi.markAllRead()
    expect(http.get).toHaveBeenNthCalledWith(1, '/notifications/mine', {
      params: { onlyUnread: true, page: 2, size: 10 },
    })
    expect(http.get).toHaveBeenNthCalledWith(2, '/notifications/mine', {
      params: { onlyUnread: true, page: 1, size: 1 },
    })
    expect(http.get).toHaveBeenNthCalledWith(3, '/notifications/mine', { params: {} })
    expect(http.patch).toHaveBeenNthCalledWith(1, '/notifications/4/read')
    expect(http.patch).toHaveBeenNthCalledWith(2, '/notifications/read-all')
  })

  it('maps optional recommendation data and default limits', async () => {
    http.get.mockResolvedValueOnce([
      { device_id: 1, name: 'popular', score: 0, reason: 'popular' },
      {
        device_id: 2, name: 'personal', category_id: 3, category_name: 'scope', lab_id: 4,
        lab_name: 'lab', score: 0.8, reason: 'history', brand: 'brand', model: 'model', status: 'IDLE',
      },
    ]).mockResolvedValueOnce([])
    await expect(recommendationApi.getRecommendations(5)).resolves.toEqual([
      {
        deviceId: 1, name: 'popular', categoryId: undefined, categoryName: undefined,
        labId: undefined, labName: undefined, score: 0, reason: 'popular', brand: undefined,
        model: undefined, status: undefined,
      },
      {
        deviceId: 2, name: 'personal', categoryId: 3, categoryName: 'scope', labId: 4,
        labName: 'lab', score: 0.8, reason: 'history', brand: 'brand', model: 'model', status: 'IDLE',
      },
    ])
    await recommendationApi.getRecommendations()
    expect(http.get).toHaveBeenNthCalledWith(1, '/recommendations', { params: { limit: 5 } })
    expect(http.get).toHaveBeenNthCalledWith(2, '/recommendations', { params: { limit: 10 } })
  })

  it('maps nullable repair fields and calls the repair lifecycle endpoints', async () => {
    const full = {
      id: 1, device_id: 2, reservation_id: 3, device_name: 'scope', reporter_id: 4,
      reporter_name: 'Reporter', title: 'fault', description: 'details', image_urls: ['/a.png'],
      status: 'PROCESSING', handler_id: 5, resolution_note: 'fixed', created_at: 'created',
      resolved_at: 'resolved', priority: 'URGENT', response_due_at: 'r', resolve_due_at: 'd',
      user_confirmed_at: 'confirmed', user_confirmation_note: 'ok', closed_at: 'closed',
    }
    const empty = {
      id: 2, device_id: 2, device_name: 'scope', reporter_id: 4, reporter_name: null,
      title: 'other', description: null, image_urls: null, status: 'PENDING', handler_id: null,
      resolution_note: null, resolved_at: null, priority: null, response_due_at: null,
      resolve_due_at: null, user_confirmed_at: null, user_confirmation_note: null, closed_at: null,
    }
    http.get.mockResolvedValueOnce({
      items: [full, empty], total: 2, page: 1, page_size: 10, pages: 1, truncated: false,
    }).mockResolvedValueOnce({
      items: [empty], total: 1, page: 2, page_size: 5, pages: 1, truncated: true,
    }).mockResolvedValueOnce([{ id: 1, status: 'PROCESSING' }])
    await expect(repairApi.myRepairs()).resolves.toMatchObject({
      records: [
        expect.objectContaining({
          reservationId: 3, reporterName: 'Reporter', handlerId: 5, priority: 'URGENT',
          imageUrls: ['/a.png'], closedAt: 'closed',
        }),
        expect.objectContaining({
          reservationId: undefined, reporterName: undefined, handlerId: undefined,
          priority: 'NORMAL', description: undefined, imageUrls: undefined, closedAt: undefined,
        }),
      ], total: 2, size: 10, current: 1, pages: 1, truncated: false,
    })
    await expect(repairApi.listRepairs('', 2, 5)).resolves.toMatchObject({
      records: [expect.objectContaining({ id: 2, priority: 'NORMAL' })], size: 5, current: 2,
    })
    await expect(repairApi.repairWorklogs(1)).resolves.toEqual([{ id: 1, status: 'PROCESSING' }])
    expect(http.get).toHaveBeenNthCalledWith(1, '/repair-reports/mine', { params: { page: 1, size: 10 } })
    expect(http.get).toHaveBeenNthCalledWith(2, '/repair-reports', {
      params: { status: undefined, page: 2, size: 5 },
    })

    const file = new File(['x'], 'evidence.png', { type: 'image/png' })
    const created = {
      deviceId: 3, title: 'noise', description: 'details', imageUrls: ['/x'], priority: undefined,
    }
    await repairApi.createRepair(created)
    await repairApi.uploadRepairImage(file)
    await repairApi.takeRepair(7)
    await repairApi.resolveRepair(7, 'fixed')
    await repairApi.rejectRepair(8, 'invalid')
    await repairApi.confirmRepair(7, true, 'works')
    expect(http.post).toHaveBeenNthCalledWith(1, '/repair-reports', {
      device_id: 3, title: 'noise', description: 'details', image_urls: ['/x'], priority: 'NORMAL',
    })
    expect(http.post.mock.calls[1][0]).toBe('/repair-uploads')
    expect((http.post.mock.calls[1][1] as FormData).get('file')).toBe(file)
    expect(http.post).toHaveBeenNthCalledWith(3, '/repair-reports/7/take')
    expect(http.post).toHaveBeenNthCalledWith(4, '/repair-reports/7/resolve', { resolution_note: 'fixed' })
    expect(http.post).toHaveBeenNthCalledWith(5, '/repair-reports/8/reject', { resolution_note: 'invalid' })
    expect(http.post).toHaveBeenNthCalledWith(6, '/repair-reports/7/confirm', { confirmed: true, note: 'works' })
  })
})
