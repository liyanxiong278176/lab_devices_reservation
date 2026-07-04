import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useCountUp } from '../useCountUp'

describe('useCountUp', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('从当前值插值到目标值', async () => {
    const target = ref(100)
    const display = useCountUp(target, { duration: 50, active: ref(true) })
    // 让 rAF 跑完 50ms 动画
    await new Promise((r) => setTimeout(r, 200))
    expect(display.value).toBeCloseTo(100, 0)
  })

  it('prefers-reduced-motion 命中时直跳目标,无动画', async () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
    }))
    const target = ref(42)
    const display = useCountUp(target, { duration: 50, active: ref(true) })
    await new Promise((r) => setTimeout(r, 30))
    expect(display.value).toBe(42)
  })

  it('active=false 时直跳目标值', async () => {
    const target = ref(99)
    const display = useCountUp(target, { duration: 50, active: ref(false) })
    await new Promise((r) => setTimeout(r, 30))
    expect(display.value).toBe(99)
  })

  it('target 变化后重新插值到新目标', async () => {
    const target = ref(50)
    const display = useCountUp(target, { duration: 50, active: ref(true) })
    await new Promise((r) => setTimeout(r, 150))
    target.value = 200
    await new Promise((r) => setTimeout(r, 200))
    expect(display.value).toBeCloseTo(200, 0)
  })
})
