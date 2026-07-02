import { useUserStore } from '@/stores/user'

/**
 * 权限/角色判断组合式函数（委托 userStore，便于在 setup 与普通 TS 中复用）。
 */
export function usePermission() {
  const u = useUserStore()

  /** 当前用户是否拥有某权限码。 */
  const hasPerm = (code: string) => u.hasPerm(code)

  /** 当前用户是否拥有某角色（如 'ADMIN'）。 */
  const hasRole = (role: string) => u.hasRole(role)

  return { hasPerm, hasRole }
}
