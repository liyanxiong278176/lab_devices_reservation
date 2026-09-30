import { afterEach, describe, expect, it, vi } from 'vitest'
import { uuid } from '../uuid'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('uuid', () => {
  it('prefers the platform randomUUID implementation', () => {
    const crypto = { randomUUID: vi.fn(() => 'platform-uuid') }
    vi.stubGlobal('crypto', crypto)

    expect(uuid()).toBe('platform-uuid')
    expect(crypto.randomUUID).toHaveBeenCalledOnce()
  })

  it('creates an RFC4122 version 4 UUID when randomUUID is unavailable', () => {
    const crypto = {
      getRandomValues: vi.fn((bytes: Uint8Array) => {
        bytes.fill(0)
        bytes[6] = 0x0f
        bytes[8] = 0x3f
        return bytes
      }),
    }
    vi.stubGlobal('crypto', crypto)

    const value = uuid()
    expect(value).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(crypto.getRandomValues).toHaveBeenCalledOnce()
  })
})
