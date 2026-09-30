import { afterAll, describe, expect, it, vi } from 'vitest'
import { createApp, h } from 'vue'

const guard = vi.hoisted(() => vi.fn(() => true))
vi.mock('../guard', () => ({ guard }))

import router, { readSpaDepth, resetSpaDepth } from '../index'

const values = new Map<string, string>()
const session = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => { values.set(key, String(value)) },
  removeItem: (key: string) => { values.delete(key) },
}

describe('router records, lazy pages and in-app navigation depth', () => {
  it('exposes the non-AI pages and loads each lazy route component', async () => {
    vi.stubGlobal('sessionStorage', session)
    Object.defineProperty(window, 'sessionStorage', { configurable: true, value: session })
    const names = router.getRoutes().map((route) => route.name).filter(Boolean)
    expect(names).toEqual(expect.arrayContaining([
      'login', 'dashboard', 'devices', 'device-detail', 'recommendations', 'reservation-create',
      'reservation-mine', 'reservation-detail', 'approvals', 'notifications', 'repair-submit',
      'repair-mine', 'repairs-admin', 'devices-manage', 'handovers', 'reports',
      'reservation-rules', 'maintenance', 'users', 'organization', 'rbac',
    ]))

    const lazyPages = router.getRoutes()
      .filter((route) => route.name !== 'ai-workbench' && route.components?.default)
    expect(lazyPages.length).toBeGreaterThan(15)
    const loaded = await Promise.all(lazyPages.map((route) =>
      (route.components!.default as () => Promise<unknown>)(),
    ))
    expect(loaded.every(Boolean)).toBe(true)

    // Keep the AI view out of feature-level coverage, while checking the shared router's lazy boundary.
    const aiRoute = router.getRoutes().find((route) => route.name === 'ai-workbench')
    expect(aiRoute?.components?.default).toBeTypeOf('function')
    const aiPageModule = await (aiRoute!.components!.default as () => Promise<unknown>)()
    expect(aiPageModule).toBeTruthy()
  }, 20000)

  it('does not count the initial page load, increments in-app navigation and supports reset', async () => {
    const app = createApp({ render: () => h('div') })
    app.use(router)
    const host = document.createElement('div')
    document.body.append(host)
    app.mount(host)
    await router.isReady()

    expect(readSpaDepth()).toBe(0)
    await router.push('/devices')
    expect(readSpaDepth()).toBe(1)
    await router.push('/reports')
    expect(readSpaDepth()).toBe(2)
    resetSpaDepth()
    expect(readSpaDepth()).toBe(0)

    app.unmount()
    host.remove()
  })
})

afterAll(() => vi.unstubAllGlobals())
