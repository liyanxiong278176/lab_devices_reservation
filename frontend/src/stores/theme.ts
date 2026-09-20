import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'lab-theme-mode'

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return 'light'
  const value = window.localStorage.getItem(STORAGE_KEY)
  return value === 'dark' ? 'dark' : 'light'
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredMode())

  function apply(next: ThemeMode = mode.value) {
    mode.value = next
    if (typeof document !== 'undefined') {
      document.documentElement.classList.toggle('dark', next === 'dark')
      document.documentElement.dataset.theme = next
    }
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
  }

  function init() {
    apply(mode.value)
  }

  function setMode(next: ThemeMode) {
    apply(next)
  }

  function toggle() {
    apply(mode.value === 'light' ? 'dark' : 'light')
  }

  return {
    mode,
    isDark: computed(() => mode.value === 'dark'),
    init,
    setMode,
    toggle,
  }
})
