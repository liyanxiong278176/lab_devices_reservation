import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const auth = vi.hoisted(() => ({
  getMe: vi.fn(), login: vi.fn(), register: vi.fn(), refresh: vi.fn(), logout: vi.fn(),
}))
vi.mock('@/api/auth', () => auth)

import { useUserStore } from '../user'

const profile = {
  id: 8, username: 'student', real_name: 'Student Name', college_id: 4,
  roles: ['STUDENT'], permissions: ['device:read', 'reservation:create'],
}

describe('user session and authorization lifecycle', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    auth.getMe.mockResolvedValue(profile)
    auth.login.mockResolvedValue({ authenticated: true })
    auth.register.mockResolvedValue({ authenticated: true })
    auth.refresh.mockResolvedValue({ authenticated: true })
    auth.logout.mockResolvedValue(undefined)
    setActivePinia(createPinia())
  })

  it('starts anonymous, initializes profile fields and checks exact permissions and roles', async () => {
    const store = useUserStore()
    expect(store.isAuthenticated).toBe(false)
    expect(store.initialized).toBe(false)
    await store.initialize()

    expect(store.isAuthenticated).toBe(true)
    expect(store.initialized).toBe(true)
    expect(store.userId).toBe(8)
    expect(store.username).toBe('student')
    expect(store.realName).toBe('Student Name')
    expect(store.collegeId).toBe(4)
    expect(store.hasPerm('device:read')).toBe(true)
    expect(store.hasPerm('device:manage')).toBe(false)
    expect(store.hasAnyPerm(['device:manage', 'reservation:create'])).toBe(true)
    expect(store.hasAnyPerm([])).toBe(false)
    expect(store.hasRole('STUDENT')).toBe(true)
    expect(store.hasRole('SYS_ADMIN')).toBe(false)
  })

  it('coalesces concurrent initialization and allows a later retry after completion', async () => {
    let resolveProfile!: (value: typeof profile) => void
    auth.getMe.mockImplementation(() => new Promise((resolve) => { resolveProfile = resolve }))
    const store = useUserStore()

    const first = store.initialize()
    const second = store.initialize()
    expect(auth.getMe).toHaveBeenCalledOnce()
    resolveProfile(profile)
    await Promise.all([first, second])
    expect(store.initialized).toBe(true)

    auth.getMe.mockResolvedValueOnce({ ...profile, id: 9 })
    await store.initialize()
    expect(auth.getMe).toHaveBeenCalledTimes(2)
    expect(store.userId).toBe(9)
  })

  it('clears stale profile on initialize failure but still marks initialization complete', async () => {
    auth.getMe.mockRejectedValue(new Error('anonymous'))
    const store = useUserStore()
    store.username = 'stale-user'
    store.roles = ['LAB_ADMIN']

    await store.initialize()

    expect(store.isAuthenticated).toBe(false)
    expect(store.username).toBe('')
    expect(store.roles).toEqual([])
    expect(store.permissions).toEqual([])
    expect(store.initialized).toBe(true)
  })

  it('logs in and registers by loading the resulting server profile', async () => {
    const store = useUserStore()
    const loginPayload = { username: 'student', password: 'pw' }
    await store.login(loginPayload)
    expect(auth.login).toHaveBeenCalledWith(loginPayload)
    expect(auth.getMe).toHaveBeenCalledOnce()
    expect(store.realName).toBe('Student Name')

    setActivePinia(createPinia())
    const next = useUserStore()
    await next.register({ ...loginPayload, real_name: 'Student Name', college_id: 4 })
    expect(auth.register).toHaveBeenCalledWith({ ...loginPayload, real_name: 'Student Name', college_id: 4 })
    expect(auth.getMe).toHaveBeenCalledTimes(2)
    expect(next.initialized).toBe(true)
  })

  it('falls back to username when the profile has no display name and exposes refresh/fetch helpers', async () => {
    auth.getMe.mockResolvedValue({ ...profile, real_name: null, college_id: null })
    const store = useUserStore()
    await store.fetchMe()
    expect(store.realName).toBe('student')
    expect(store.collegeId).toBeNull()
    await store.refresh()
    expect(auth.refresh).toHaveBeenCalledOnce()
  })

  it('skips remote logout when anonymous and always clears profile when logout fails', async () => {
    const store = useUserStore()
    await store.logout()
    expect(auth.logout).not.toHaveBeenCalled()
    expect(store.initialized).toBe(true)

    store.userId = 8
    store.username = 'student'
    auth.logout.mockRejectedValueOnce(new Error('network'))
    await expect(store.logout()).rejects.toThrow('network')
    expect(auth.logout).toHaveBeenCalledOnce()
    expect(store.isAuthenticated).toBe(false)
    expect(store.username).toBe('')
    expect(store.initialized).toBe(true)
  })
})
