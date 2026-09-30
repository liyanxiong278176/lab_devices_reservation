import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from '@/stores/user'
import { usePermission } from '../usePermission'

describe('usePermission', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('uses permission codes returned by the server', () => {
    const user = useUserStore()
    user.permissions = ['device:manage', 'reservation:approve']
    const { hasPerm } = usePermission()
    expect(hasPerm('device:manage')).toBe(true)
    expect(hasPerm('reservation:approve')).toBe(true)
  })

  it('does not grant a permission that is absent from the profile', () => {
    const user = useUserStore()
    user.permissions = ['reservation:approve']
    const { hasPerm } = usePermission()
    expect(hasPerm('device:manage')).toBe(false)
  })

  it('matches role codes exactly for display-only role checks', () => {
    const user = useUserStore()
    user.roles = ['USER']
    const { hasRole } = usePermission()
    expect(hasRole('USER')).toBe(true)
    expect(hasRole('ADMIN')).toBe(false)
  })

  it('uses server-provided permissions for a system administrator', () => {
    const user = useUserStore()
    user.roles = ['SYS_ADMIN']
    user.permissions = ['reservation:approve', 'device:manage', 'repair:handle']
    const { hasPerm } = usePermission()
    expect(hasPerm('reservation:approve')).toBe(true)
    expect(hasPerm('device:manage')).toBe(true)
    expect(hasPerm('repair:handle')).toBe(true)
  })

  it('does not infer administrator permissions for an ordinary user', () => {
    const user = useUserStore()
    user.roles = ['STUDENT']
    const { hasPerm } = usePermission()
    expect(hasPerm('reservation:approve')).toBe(false)
    expect(hasPerm('device:manage')).toBe(false)
    expect(hasPerm('repair:handle')).toBe(false)
  })
})
