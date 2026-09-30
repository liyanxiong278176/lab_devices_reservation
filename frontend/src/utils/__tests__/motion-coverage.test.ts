import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => vi.unstubAllGlobals())

describe('reduced-motion utility environment and subscription branches', () => {
  it('returns false during server rendering or when matchMedia is unavailable', async () => {
    vi.stubGlobal('window', undefined)
    let motion = await import('../motion')
    expect(motion.prefersReducedMotion()).toBe(false)

    vi.resetModules()
    vi.stubGlobal('window', { matchMedia: undefined })
    motion = await import('../motion')
    expect(motion.prefersReducedMotion()).toBe(false)
  })

  it('reads the initial preference, shares the ref and follows changes while rebinding replaced APIs', async () => {
    vi.resetModules()
    let handler: ((event: { matches: boolean }) => void) | undefined
    const first = {
      matches: true,
      addEventListener: vi.fn((_event: string, next: (event: { matches: boolean }) => void) => { handler = next }),
      removeEventListener: vi.fn(),
    }
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => first) })
    const motion = await import('../motion')

    const shared = motion.useReducedMotion()
    expect(shared.value).toBe(true)
    expect(motion.prefersReducedMotion()).toBe(true)
    expect(first.addEventListener).toHaveBeenCalledOnce()
    handler?.({ matches: false })
    expect(shared.value).toBe(false)

    const second = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => second) })
    expect(motion.prefersReducedMotion()).toBe(false)
    expect(first.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function))
    expect(second.addEventListener).toHaveBeenCalledOnce()
  })

  it('accepts a media-query object without event subscription APIs', async () => {
    vi.resetModules()
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: true }) })
    const motion = await import('../motion')
    expect(motion.useReducedMotion().value).toBe(true)
  })
})
