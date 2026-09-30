import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'

const motion = vi.hoisted(() => ({ reduced: undefined as { value: boolean } | undefined }))
vi.mock('@/utils/motion', async () => {
  const { ref } = await import('vue')
  motion.reduced = ref(false)
  return { useReducedMotion: () => motion.reduced! }
})

import { useCountUp } from '../useCountUp'

afterEach(() => {
  if (motion.reduced) motion.reduced.value = false
  vi.unstubAllGlobals()
})

describe('count-up animation lifecycle boundaries', () => {
  it('uses defaults, skips equal targets and finishes interpolation at the target', async () => {
    let now = 0
    const callbacks: FrameRequestCallback[] = []
    vi.stubGlobal('performance', { now: () => now })
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      callbacks.push(callback)
      return callbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const target = ref(0)
    const scope = effectScope()
    let display!: ReturnType<typeof ref<number>>
    scope.run(() => { display = useCountUp(target) })

    expect(display.value).toBe(0)
    expect(callbacks).toHaveLength(0)
    target.value = 100
    await nextTick()
    expect(callbacks).toHaveLength(1)

    now = 500
    callbacks[0](999999)
    expect(display.value).toBeGreaterThan(90)
    expect(display.value).toBeLessThan(100)
    now = 1000
    callbacks[1](999999)
    expect(display.value).toBe(100)
    scope.stop()
  })

  it('cancels an active frame and jumps to the target when reduced motion turns on', async () => {
    let nextId = 0
    const cancel = vi.fn()
    vi.stubGlobal('performance', { now: () => 10 })
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => ++nextId))
    vi.stubGlobal('cancelAnimationFrame', cancel)
    const target = ref(42)
    const scope = effectScope()
    let display!: ReturnType<typeof ref<number>>
    scope.run(() => { display = useCountUp(target, { duration: 100 }) })
    expect(nextId).toBe(1)

    motion.reduced!.value = true
    await nextTick()
    expect(cancel).toHaveBeenCalledWith(1)
    expect(display.value).toBe(42)
    scope.stop()
  })

  it('cancels a pending animation when its effect scope is disposed', () => {
    const cancel = vi.fn()
    vi.stubGlobal('performance', { now: () => 1 })
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 17))
    vi.stubGlobal('cancelAnimationFrame', cancel)
    const scope = effectScope()
    scope.run(() => useCountUp(ref(8)))
    scope.stop()
    expect(cancel).toHaveBeenCalledWith(17)
  })
})
