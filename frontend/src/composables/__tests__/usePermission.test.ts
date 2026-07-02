import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import { usePermission } from '../usePermission'

describe('usePermission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('hasPerm 返回 true 当用户拥有该权限码', () => {
    const u = useUserStore()
    u.permissions = ['device:manage', 'device:approve']
    const { hasPerm } = usePermission()
    expect(hasPerm('device:manage')).toBe(true)
    expect(hasPerm('device:approve')).toBe(true)
  })

  it('hasPerm 返回 false 当用户缺少该权限码', () => {
    const u = useUserStore()
    u.permissions = ['device:approve']
    const { hasPerm } = usePermission()
    expect(hasPerm('device:manage')).toBe(false)
  })

  it('hasRole 按 role 字符串精确匹配', () => {
    const u = useUserStore()
    u.roles = ['USER']
    const { hasRole } = usePermission()
    expect(hasRole('USER')).toBe(true)
    expect(hasRole('ADMIN')).toBe(false)
  })
})
