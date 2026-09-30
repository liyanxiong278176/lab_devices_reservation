import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const user = vi.hoisted(() => ({ hasRole: vi.fn() }))
vi.mock('@/stores/user', () => ({ useUserStore: () => user }))
vi.mock('../Student.vue', () => ({ __esModule: true, default: { name: 'StudentDashboardStub', template: '<div data-role="student" />' } }))
vi.mock('../LabAdmin.vue', () => ({ __esModule: true, default: { name: 'LabAdminDashboardStub', template: '<div data-role="lab-admin" />' } }))
vi.mock('../Admin.vue', () => ({ __esModule: true, default: { name: 'SystemAdminDashboardStub', template: '<div data-role="system-admin" />' } }))

import Dashboard from '../Index.vue'

describe('dashboard role dispatch', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    [['STUDENT'], 'student'],
    [['LAB_ADMIN'], 'lab-admin'],
    [['SYS_ADMIN'], 'system-admin'],
  ])('selects the dashboard for role set %j', async (roles, expected) => {
    user.hasRole.mockImplementation((role: string) => roles.includes(role))
    const wrapper = mount(Dashboard)
    await flushPromises()

    expect(wrapper.find(`[data-role="${expected}"]`).exists()).toBe(true)
    expect(user.hasRole).toHaveBeenCalledWith('STUDENT')
    if (expected !== 'student') expect(user.hasRole).toHaveBeenCalledWith('LAB_ADMIN')
  })
})
