import { beforeEach, describe, expect, it, vi } from 'vitest'

const user = vi.hoisted(() => ({
  initialized: false, isAuthenticated: false, initialize: vi.fn(), hasAnyPerm: vi.fn(),
}))
vi.mock('@/stores/user', () => ({ useUserStore: () => user }))

import { guard } from '../guard'

const target = (overrides: Record<string, unknown> = {}) => ({
  meta: {}, fullPath: '/devices?lab=7', ...overrides,
})
const runGuard = (to: unknown) => guard.call(undefined, to as never, {} as never, vi.fn() as never)

describe('route permission guard', () => {
  beforeEach(() => {
    user.initialized = false
    user.isAuthenticated = false
    vi.clearAllMocks()
    user.initialize.mockImplementation(async () => { user.initialized = true })
    user.hasAnyPerm.mockReturnValue(false)
  })

  it('allows public routes without initializing a session', async () => {
    await expect(runGuard(target({ meta: { public: true } }))).resolves.toBe(true)
    expect(user.initialize).not.toHaveBeenCalled()
  })

  it('initializes unknown session state, then redirects anonymous users with the original path', async () => {
    const result = await runGuard(target())
    expect(user.initialize).toHaveBeenCalledOnce()
    expect(result).toEqual({ path: '/login', query: { redirect: '/devices?lab=7' } })
  })

  it('redirects authenticated users lacking required scope and allows matching or unrestricted routes', async () => {
    user.initialized = true
    user.isAuthenticated = true
    const denied = await runGuard(target({ meta: { permissions: ['device:manage'] } }))
    expect(denied).toEqual({ path: '/dashboard' })
    expect(user.hasAnyPerm).toHaveBeenCalledWith(['device:manage'])

    user.hasAnyPerm.mockReturnValue(true)
    await expect(runGuard(target({ meta: { permissions: ['device:read'] } }))).resolves.toBe(true)
    await expect(runGuard(target({ meta: { permissions: [] } }))).resolves.toBe(true)
    await expect(runGuard(target())).resolves.toBe(true)
  })
})
