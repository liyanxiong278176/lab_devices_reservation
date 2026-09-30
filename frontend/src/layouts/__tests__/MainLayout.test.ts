import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'

const permissions = vi.hoisted(() => ['dashboard:read', 'notification:read:own'])
const user = vi.hoisted(() => ({
  realName: '林同学', username: 'lin',
  hasAnyPerm: vi.fn((codes: string[]) => codes.some((code) => permissions.includes(code))),
  logout: vi.fn(),
}))
const router = vi.hoisted(() => ({
  options: { routes: [{ path: '/', children: [] as Array<Record<string, any>> }] },
  push: vi.fn(),
}))
const route = vi.hoisted(() => ({ path: '/dashboard' }))
const notifications = vi.hoisted(() => ({ unread: 4, loadUnread: vi.fn() }))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const eventStreams = vi.hoisted(() => ({ connectEventStream: vi.fn(), disconnectEventStream: vi.fn() }))

vi.mock('@/stores/user', async () => {
  const { reactive } = await import('vue')
  return { useUserStore: () => reactive(user) }
})
vi.mock('@/stores/notification', () => ({ useNotificationStore: () => notifications }))
vi.mock('@/stores/theme', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ isDark: false, toggle() { state.isDark = !state.isDark } })
  return { useThemeStore: () => state }
})
vi.mock('vue-router', () => ({ useRouter: () => router, useRoute: () => route }))
vi.mock('element-plus', () => ({ ElMessage: messages }))
vi.mock('@/composables/useEventStream', () => eventStreams)

import MainLayout from '../MainLayout.vue'

enableAutoUnmount(afterEach)

const stubs = {
  'el-container': { template: '<div class="container-stub"><slot /></div>' },
  'el-aside': { template: '<aside><slot /></aside>' },
  'el-header': { template: '<header><slot /></header>' },
  'el-main': { template: '<main><slot /></main>' },
  'el-menu': { props: ['defaultActive'], template: '<nav :data-active="defaultActive"><slot /></nav>' },
  'el-menu-item': {
    props: ['index', 'ariaLabel'],
    template: '<a class="menu-item" :data-index="index" :aria-label="ariaLabel"><slot /><slot name="title" /></a>',
  },
  'el-icon': { template: '<i><slot /></i>' },
  'el-badge': {
    props: ['value', 'hidden'],
    template: '<span class="badge" :data-value="value" :data-hidden="hidden"><slot /></span>',
  },
  'el-button': {
    inheritAttrs: false,
    template: '<button class="logout-button" @click="$emit(\'click\')"><slot /></button>',
  },
  'router-view': { template: '<div class="nested-route" />' },
}

function routes() {
  router.options.routes[0].children = [
    { path: 'dashboard', meta: { title: 'Dashboard', icon: 'Odometer', permissions: ['dashboard:read'] } },
    { path: 'hidden', meta: { title: 'Hidden', hidden: true } },
    { path: 'denied', meta: { title: 'Denied', permissions: ['user:manage'] } },
    { path: 'public', meta: { title: 'Public' } },
    { path: 'empty-permission', meta: { title: 'No permission needed', permissions: [] } },
    { path: 'untitled', meta: { hidden: false } },
  ]
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('main application layout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    permissions.splice(0, permissions.length, 'dashboard:read', 'notification:read:own')
    user.realName = '林同学'
    user.username = 'lin'
    user.logout.mockResolvedValue(undefined)
    router.push.mockResolvedValue(undefined)
    route.path = '/dashboard'
    notifications.unread = 4
    router.options.routes = [{ path: '/', children: [] }]
    routes()
  })

  it('filters menu entries by title, hidden flag and current permissions', async () => {
    const wrapper = mount(MainLayout, { global: { stubs } })
    await flushPromises()

    expect(wrapper.findAll('.menu-item').map((item) => item.attributes('data-index'))).toEqual([
      '/dashboard', '/public', '/empty-permission',
    ])
    expect(wrapper.find('nav').attributes('data-active')).toBe('/dashboard')
    expect(wrapper.find('.layout__user-name').text()).toBe('林同学')
    expect(wrapper.find('.badge').attributes('data-value')).toBe('4')
    expect(wrapper.find('.badge').attributes('data-hidden')).toBe('false')
    expect(user.hasAnyPerm).toHaveBeenCalledWith(['user:manage'])
  })

  it('uses username and generic fallbacks when a profile lacks display fields', () => {
    user.realName = ''
    const byUsername = mount(MainLayout, { global: { stubs } })
    expect(byUsername.find('.layout__user-name').text()).toBe('lin')

    user.username = ''
    const generic = mount(MainLayout, { global: { stubs } })
    expect(generic.find('.layout__user-name').text()).toBe('用户')
  })

  it('handles an absent root route and hides a zero unread badge', () => {
    router.options.routes = []
    notifications.unread = 0
    const wrapper = mount(MainLayout, { global: { stubs } })
    expect(wrapper.findAll('.menu-item')).toHaveLength(0)
    expect(wrapper.find('.badge').attributes('data-hidden')).toBe('true')
  })

  it('handles a root route without children and unmounts when no interval was allocated', () => {
    router.options.routes = [{ path: '/' } as any]
    vi.stubGlobal('setInterval', vi.fn(() => null))
    const wrapper = mount(MainLayout, { global: { stubs } })

    expect(wrapper.findAll('.menu-item')).toHaveLength(0)
    wrapper.unmount()
    expect(eventStreams.disconnectEventStream).toHaveBeenCalledOnce()
  })

  it('loads unread state, connects realtime, periodically refreshes and cleans up', async () => {
    vi.useFakeTimers()
    const wrapper = mount(MainLayout, { global: { stubs } })
    expect(notifications.loadUnread).toHaveBeenCalledOnce()
    expect(eventStreams.connectEventStream).toHaveBeenCalledOnce()

    await vi.advanceTimersByTimeAsync(30000)
    expect(notifications.loadUnread).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect(eventStreams.disconnectEventStream).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(60000)
    expect(notifications.loadUnread).toHaveBeenCalledTimes(2)
  })

  it('toggles theme, navigates to notifications and logs out successfully', async () => {
    const wrapper = mount(MainLayout, { global: { stubs } })
    const theme = wrapper.get('.layout__theme-toggle')
    expect(theme.attributes('aria-label')).toBe('切换深色')
    await theme.trigger('click')
    expect(theme.attributes('aria-label')).toBe('切换浅色')

    await wrapper.get('.layout__icon-button').trigger('click')
    expect(router.push).toHaveBeenCalledWith('/notifications')
    await wrapper.get('.logout-button').trigger('click')
    await flushPromises()
    expect(user.logout).toHaveBeenCalledOnce()
    expect(messages.success).toHaveBeenCalledWith('已退出登录')
    expect(router.push).toHaveBeenLastCalledWith('/login')
  })

  it('redirects to login in the logout finally path even when session termination fails', async () => {
    user.logout.mockRejectedValue(new Error('logout failed'))
    const errors: unknown[] = []
    const wrapper = mount(MainLayout, {
      global: { stubs, config: { errorHandler: (error) => errors.push(error) } },
    })
    await wrapper.get('.logout-button').trigger('click')
    await flushPromises()

    expect(router.push).toHaveBeenCalledWith('/login')
    expect(messages.success).not.toHaveBeenCalled()
    expect(errors).toHaveLength(1)
  })
})
