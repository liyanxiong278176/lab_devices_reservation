import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAppStore } from '../app'
import { useThemeStore } from '../theme'

const values = new Map<string, string>()
const storage = {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => { values.set(key, String(value)) },
  removeItem: (key: string) => { values.delete(key) },
  clear: () => values.clear(),
}

describe('application shell and theme stores', () => {
  beforeEach(() => {
    values.clear()
    vi.stubGlobal('localStorage', storage)
    Object.defineProperty(window, 'localStorage', { configurable: true, value: storage })
    document.documentElement.classList.remove('dark')
    delete document.documentElement.dataset.theme
    setActivePinia(createPinia())
  })

  it('toggles the navigation rail between compact and expanded states', () => {
    const store = useAppStore()
    expect(store.sidebarCollapsed).toBe(true)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(false)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(true)
  })

  it('initializes light mode and writes theme state to the document and storage', () => {
    const store = useThemeStore()
    expect(store.mode).toBe('light')
    expect(store.isDark).toBe(false)

    store.init()
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('lab-theme-mode')).toBe('light')

    store.setMode('dark')
    expect(store.isDark).toBe(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('lab-theme-mode')).toBe('dark')
  })

  it('restores a saved dark mode and toggles in both directions', () => {
    localStorage.setItem('lab-theme-mode', 'dark')
    setActivePinia(createPinia())
    const store = useThemeStore()
    expect(store.mode).toBe('dark')
    expect(store.isDark).toBe(true)

    store.toggle()
    expect(store.mode).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    store.toggle()
    expect(store.mode).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('falls back to light mode for an unknown persisted value', () => {
    localStorage.setItem('lab-theme-mode', 'system')
    setActivePinia(createPinia())
    expect(useThemeStore().mode).toBe('light')
  })
})
