import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

describe('theme store server rendering fallbacks', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('defaults to light and updates state without browser globals', async () => {
    vi.stubGlobal('window', undefined)
    vi.stubGlobal('document', undefined)
    vi.resetModules()

    const { useThemeStore } = await import('../theme')
    setActivePinia(createPinia())
    const store = useThemeStore()

    expect(store.mode).toBe('light')
    store.setMode('dark')
    expect(store.mode).toBe('dark')
    store.toggle()
    expect(store.mode).toBe('light')
  })
})
