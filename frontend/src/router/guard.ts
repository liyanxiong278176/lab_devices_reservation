import type { NavigationGuardWithThis } from 'vue-router'
import { useUserStore } from '@/stores/user'

export const guard: NavigationGuardWithThis<undefined> = async (to) => {
  const u = useUserStore()
  if (to.meta.public) return true
  if (!u.initialized) await u.initialize()
  if (!u.isAuthenticated) return { path: '/login', query: { redirect: to.fullPath } }
  const permissions = to.meta.permissions as string[] | undefined
  if (permissions?.length && !u.hasAnyPerm(permissions)) return { path: '/dashboard' }
  return true
}
