import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  // The product shell opens as a compact navigation rail. Users can expand it
  // when they need labels, while the canvas remains the visual focus by default.
  const sidebarCollapsed = ref(true)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return { sidebarCollapsed, toggleSidebar }
})
