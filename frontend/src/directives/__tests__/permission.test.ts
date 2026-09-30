import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ObjectDirective } from 'vue'

const user = vi.hoisted(() => ({ hasPerm: vi.fn() }))
vi.mock('@/stores/user', () => ({ useUserStore: () => user }))

import { vPermission } from '../permission'

const objectDirective = vPermission as ObjectDirective<HTMLElement, string | string[]>

describe('v-permission directive', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('keeps an element when its single permission is granted', () => {
    user.hasPerm.mockReturnValue(true)
    const parent = document.createElement('div')
    const element = document.createElement('button')
    parent.append(element)

    objectDirective.mounted?.(element, { value: 'device:manage' } as never, {} as never, null)

    expect(user.hasPerm).toHaveBeenCalledWith('device:manage')
    expect(element.parentNode).toBe(parent)
  })

  it('keeps an element when any requested permission is granted', () => {
    user.hasPerm.mockImplementation((code: string) => code === 'reservation:approve')
    const element = document.createElement('button')
    document.body.append(element)

    objectDirective.mounted?.(element, { value: ['device:manage', 'reservation:approve'] } as never, {} as never, null)

    expect(user.hasPerm).toHaveBeenNthCalledWith(1, 'device:manage')
    expect(user.hasPerm).toHaveBeenNthCalledWith(2, 'reservation:approve')
    expect(element.parentNode).toBe(document.body)
    element.remove()
  })

  it('removes an element when none of its permissions are granted', () => {
    user.hasPerm.mockReturnValue(false)
    const parent = document.createElement('div')
    const element = document.createElement('button')
    parent.append(element)

    objectDirective.mounted?.(element, { value: ['device:manage', 'repair:handle'] } as never, {} as never, null)

    expect(element.parentNode).toBeNull()
  })

  it('tolerates removing an unauthorized element that is already detached', () => {
    user.hasPerm.mockReturnValue(false)
    const element = document.createElement('button')

    expect(() => objectDirective.mounted?.(element, { value: 'admin:all' } as never, {} as never, null)).not.toThrow()
    expect(element.parentNode).toBeNull()
  })
})
