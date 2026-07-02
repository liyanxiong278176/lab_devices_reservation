import type { NavigationGuardWithThis } from 'vue-router'
import { useUserStore } from '@/stores/user'

export const guard: NavigationGuardWithThis<undefined> = (to) => {
  const u = useUserStore()
  if (to.meta.public) return true
  if (!u.accessToken) return { path: '/login', query: { redirect: to.fullPath } }
  const need = to.meta.roles as string[] | undefined
  if (need && need.length && !need.some((r) => u.roles.includes(r))) return false
  return true
}
