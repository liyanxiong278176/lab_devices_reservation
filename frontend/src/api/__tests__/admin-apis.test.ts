import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
  defaults: { baseURL: '/api/v2/' },
}))

vi.mock('../request', () => ({ default: http }))

import * as approvalApi from '../approval'
import * as collegeApi from '../college'
import * as dashboardApi from '../dashboard'
import * as rbacApi from '../rbac'
import * as reportApi from '../reports'
import * as reservationRuleApi from '../reservationRules'
import * as schedulingApi from '../scheduling'
import * as userApi from '../user'

describe('administrative API contracts', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    http.get.mockResolvedValue(undefined)
    http.post.mockResolvedValue(undefined)
    http.put.mockResolvedValue(undefined)
    http.patch.mockResolvedValue(undefined)
    http.delete.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('maps pending approval rows and keeps the optional username fallback', async () => {
    http.get.mockResolvedValueOnce({
      items: [
        {
          id: 1, user_id: 20, device_id: 8, device_name: 'scope',
          start_date: '2026-09-30', end_date: '2026-10-01', dates: ['a', 'b'],
          status: 'PENDING',
        },
        {
          id: 2, user_id: 21, username: 'student', real_name: 'Student', device_id: 9,
          device_name: 'microscope', purpose: 'lab work', start_date: '2026-10-02',
          end_date: '2026-10-02', dates: ['a'], status: 'PENDING', created_at: 'now',
        },
      ],
      total: 2, page: 3, page_size: 10, pages: 4, truncated: true,
    })

    await expect(approvalApi.pendingApprovals(3, 10)).resolves.toEqual({
      records: [
        expect.objectContaining({
          id: 1, userId: 20, username: 'user-20', startTime: '2026-09-30T00:00:00',
          endTime: '2026-10-01T23:59:59', slotCount: 2,
        }),
        expect.objectContaining({
          id: 2, username: 'student', realName: 'Student', purpose: 'lab work',
          slotCount: 1, createdAt: 'now',
        }),
      ],
      total: 2, size: 10, current: 3, pages: 4, truncated: true,
    })
    expect(http.get).toHaveBeenCalledWith('/approvals/pending', { params: { page: 3, page_size: 10 } })

    await approvalApi.approve(4)
    await approvalApi.reject(5, 'outside scope')
    await approvalApi.batchApprove([6, 7])
    expect(http.post.mock.calls).toEqual([
      ['/approvals/4/approve', {}],
      ['/approvals/5/reject', { reason: 'outside scope' }],
      ['/approvals/batch-approve', { ids: [6, 7] }],
    ])
  })

  it('maps colleges and managers and serializes missing manager ids as null', async () => {
    http.get
      .mockResolvedValueOnce([{ id: 1, code: 'ENG', name: 'Engineering' }])
      .mockResolvedValueOnce([{ id: 2, username: 'lead', college_id: 1 }])

    await expect(collegeApi.listColleges()).resolves.toEqual([
      { id: 1, code: 'ENG', name: 'Engineering', managerId: undefined, managerName: undefined },
    ])
    await expect(collegeApi.listManagers(1)).resolves.toEqual([
      { id: 2, username: 'lead', realName: undefined, collegeId: 1 },
    ])
    expect(http.get).toHaveBeenNthCalledWith(2, '/organization/managers', { params: { college_id: 1 } })

    const payload = { code: 'SCI', name: 'Science', managerId: 12 }
    await collegeApi.createCollege(payload)
    await collegeApi.updateCollege(7, { code: 'ART', name: 'Art' })
    expect(http.post).toHaveBeenCalledWith('/colleges', { code: 'SCI', name: 'Science', manager_id: 12 })
    expect(http.put).toHaveBeenCalledWith('/colleges/7', { code: 'ART', name: 'Art', manager_id: null })
  })

  it('calls dashboard endpoints with and without overview filters', async () => {
    const overview = { cards: { todayReservations: 1 } }
    const mine = { unreadCount: 4 }
    http.get.mockResolvedValueOnce(overview).mockResolvedValueOnce(mine).mockResolvedValueOnce({})

    await expect(dashboardApi.dashboardOverview({ groupBy: 'category', days: 14 })).resolves.toBe(overview)
    await expect(dashboardApi.dashboardOverview()).resolves.toBe(mine)
    await expect(dashboardApi.dashboardMe()).resolves.toEqual({})
    await dashboardApi.summary()
    expect(http.get).toHaveBeenNthCalledWith(1, '/dashboard/overview', {
      params: { groupBy: 'category', days: 14 },
    })
    expect(http.get).toHaveBeenNthCalledWith(2, '/dashboard/overview', { params: {} })
    expect(http.get).toHaveBeenNthCalledWith(3, '/dashboard/me')
    expect(http.get).toHaveBeenNthCalledWith(4, '/dashboard/summary')
  })

  it('covers role and permission operations', async () => {
    await rbacApi.listPermissions()
    await rbacApi.listRoles()
    await rbacApi.createRole({ role_code: 'HELPER', role_name: 'Helper', permission_codes: ['device:read'] })
    await rbacApi.renameRole(3, 'Lab helper')
    await rbacApi.updateRolePermissions(3, ['device:read', 'reservation:read:own'])
    await rbacApi.deleteRole(3)
    expect(http.get.mock.calls).toEqual([
      ['/rbac/permissions'], ['/rbac/roles'],
    ])
    expect(http.post).toHaveBeenCalledWith('/rbac/roles', {
      role_code: 'HELPER', role_name: 'Helper', permission_codes: ['device:read'],
    })
    expect(http.patch).toHaveBeenCalledWith('/rbac/roles/3', { role_name: 'Lab helper' })
    expect(http.put).toHaveBeenCalledWith('/rbac/roles/3/permissions', {
      permission_codes: ['device:read', 'reservation:read:own'],
    })
    expect(http.delete).toHaveBeenCalledWith('/rbac/roles/3')
  })

  it('maps reservation rules and preserves nullable policy values', async () => {
    const rule = {
      id: 2, scope_type: 'COLLEGE', scope_id: 9, scope_name: 'Science',
      user_category: 'STUDENT', max_booking_days: null, max_advance_days: 20,
      approval_required: false,
    }
    http.get.mockResolvedValueOnce({
      items: [rule], total: 1, page: 2, page_size: 5, pages: 1, truncated: false,
    })
    await expect(reservationRuleApi.listReservationRules(2, 5, {
      scopeType: 'COLLEGE', userCategory: 'STUDENT', scopeId: 9,
    })).resolves.toEqual({
      items: [{
        id: 2, scopeType: 'COLLEGE', scopeId: 9, scopeName: 'Science',
        userCategory: 'STUDENT', maxBookingDays: null, maxAdvanceDays: 20,
        approvalRequired: false,
      }],
      total: 1, page: 2, pageSize: 5, pages: 1, truncated: false,
    })
    expect(http.get).toHaveBeenCalledWith('/reservation-rules', {
      params: { page: 2, page_size: 5, scope_type: 'COLLEGE', user_category: 'STUDENT', scope_id: 9 },
    })

    http.put.mockResolvedValueOnce(rule)
    await reservationRuleApi.saveReservationRule({
      scopeType: 'COLLEGE', scopeId: 9, userCategory: 'STUDENT',
      maxBookingDays: null, maxAdvanceDays: 20, approvalRequired: false,
    })
    await reservationRuleApi.deleteReservationRule(2)
    expect(http.put).toHaveBeenCalledWith('/reservation-rules', {
      scope_type: 'COLLEGE', scope_id: 9, user_category: 'STUDENT',
      max_booking_days: null, max_advance_days: 20, approval_required: false,
    })
    expect(http.delete).toHaveBeenCalledWith('/reservation-rules/2')
  })

  it('maps blackout rows and handles absent list filters', async () => {
    http.get.mockResolvedValueOnce([{
      id: 1, scope_type: 'LAB', scope_id: 3, scope_name: null,
      blocked_date: '2026-10-01', reason: 'maintenance', active: true,
    }]).mockResolvedValueOnce([])
    await expect(schedulingApi.listBlackouts({ startDate: '2026-10-01', endDate: '2026-10-02' }))
      .resolves.toEqual([{
        id: 1, scopeType: 'LAB', scopeId: 3, scopeName: null,
        blockedDate: '2026-10-01', reason: 'maintenance', active: true, createdAt: undefined,
      }])
    await expect(schedulingApi.listBlackouts()).resolves.toEqual([])
    expect(http.get).toHaveBeenNthCalledWith(1, '/blackouts', {
      params: { start_date: '2026-10-01', end_date: '2026-10-02' },
    })
    expect(http.get).toHaveBeenNthCalledWith(2, '/blackouts', {
      params: { start_date: undefined, end_date: undefined },
    })

    http.post.mockResolvedValueOnce({
      id: 5, scope_type: 'DEVICE', scope_id: 10, blocked_date: '2026-10-03',
      reason: 'repair', active: true, created_at: 'now',
    })
    await expect(schedulingApi.createBlackout({
      scopeType: 'DEVICE', scopeId: 10, blockedDate: '2026-10-03', reason: 'repair',
    })).resolves.toMatchObject({ id: 5, scopeType: 'DEVICE', scopeName: undefined, createdAt: 'now' })
    await schedulingApi.deleteBlackout(5)
    expect(http.post).toHaveBeenCalledWith('/blackouts', {
      scope_type: 'DEVICE', scope_id: 10, blocked_date: '2026-10-03', reason: 'repair',
    })
    expect(http.delete).toHaveBeenCalledWith('/blackouts/5')
  })

  it('maps users and serializes CRUD and status operations', async () => {
    http.get.mockResolvedValueOnce({
      records: [
        { id: 1, username: 'student', status: 1, roles: ['STUDENT'] },
        {
          id: 2, username: 'admin', real_name: 'Admin', phone: '100', email: 'a@b.test',
          user_type: 'STAFF', college_id: 6, status: 1, roles: ['SYS_ADMIN'], created_at: 'today',
        },
      ],
      total: 2, size: 10, current: 1, pages: 1, truncated: false,
    })
    await expect(userApi.listUsers({ username: 'admin', realName: 'Admin', status: 1, page: 1, size: 10 }))
      .resolves.toEqual({
        records: [
          { id: 1, username: 'student', realName: undefined, phone: undefined, email: undefined,
            userType: undefined, collegeId: undefined, status: 1, roles: ['STUDENT'], createdAt: undefined },
          { id: 2, username: 'admin', realName: 'Admin', phone: '100', email: 'a@b.test',
            userType: 'STAFF', collegeId: 6, status: 1, roles: ['SYS_ADMIN'], createdAt: 'today' },
        ], total: 2, size: 10, current: 1, pages: 1, truncated: false,
      })
    expect(http.get).toHaveBeenCalledWith('/users', {
      params: { username: 'admin', real_name: 'Admin', status: 1, page: 1, size: 10 },
    })

    const payload = {
      username: 'new-user', password: 'secret', realName: 'New User', phone: '123',
      email: 'new@b.test', userType: 'STUDENT', roleCodes: ['STUDENT'], collegeId: 6,
    }
    await userApi.createUser(payload)
    await userApi.updateUser(8, payload)
    await userApi.deleteUser(8)
    await userApi.patchUserStatus(8, 0)
    const expected = {
      username: 'new-user', password: 'secret', real_name: 'New User', phone: '123',
      email: 'new@b.test', user_type: 'STUDENT', role_codes: ['STUDENT'], college_id: 6,
    }
    expect(http.post).toHaveBeenCalledWith('/users', expected)
    expect(http.put).toHaveBeenCalledWith('/users/8', expected)
    expect(http.delete).toHaveBeenCalledWith('/users/8')
    expect(http.patch).toHaveBeenCalledWith('/users/8/status', null, { params: { status: 0 } })
  })

  it('downloads report blobs and builds report query parameters for full and empty filters', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const createObjectURL = vi.fn(() => 'blob:report')
    const revokeObjectURL = vi.fn()
    const urlDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })

    try {
      const blob = new Blob(['csv'])
      http.get.mockResolvedValueOnce({ count: 1 }).mockResolvedValueOnce(blob)
        .mockResolvedValueOnce({ id: 4 }).mockResolvedValueOnce(blob)
      await reportApi.getReportSummary({
        startDate: '2026-09-01', endDate: '2026-09-30', status: 'COMPLETED', collegeId: 2,
      })
      await reportApi.getReportSummary()
      await reportApi.downloadReport('repairs', { startDate: '2026-09-01' })
      await reportApi.createReportExport('devices', { status: 'ACTIVE', collegeId: 3 })
      await reportApi.getReportExport(4)
      await reportApi.downloadReportExport(4, 'reservations')

      expect(http.get).toHaveBeenNthCalledWith(1, '/reports/summary', {
        params: { start_date: '2026-09-01', end_date: '2026-09-30', status: 'COMPLETED', college_id: 2 },
      })
      expect(http.get).toHaveBeenNthCalledWith(2, '/reports/summary', {
        params: { start_date: undefined, end_date: undefined, status: undefined, college_id: undefined },
      })
      expect(http.get).toHaveBeenNthCalledWith(3, '/reports/export/repairs', {
        params: { start_date: '2026-09-01', end_date: undefined, status: undefined, college_id: undefined },
        responseType: 'blob',
      })
      expect(http.post).toHaveBeenCalledWith('/reports/exports', {
        export_type: 'devices', start_date: undefined, end_date: undefined, status: 'ACTIVE', college_id: 3,
      })
      expect(http.get).toHaveBeenNthCalledWith(4, '/reports/exports/4')
      expect(http.get).toHaveBeenNthCalledWith(5, '/reports/exports/4/download', { responseType: 'blob' })
      expect(click).toHaveBeenCalledTimes(2)
      expect(createObjectURL).toHaveBeenCalledTimes(2)
      expect(revokeObjectURL).toHaveBeenNthCalledWith(1, 'blob:report')
    } finally {
      if (urlDescriptor) Object.defineProperty(URL, 'createObjectURL', urlDescriptor)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (revokeDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })
})
