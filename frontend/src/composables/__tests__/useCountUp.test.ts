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

  it('holdWhenInactive=true 且 active=false 时,display 保持在初值(不跳 target)', async () => {
    // 显式 stub matchMedia matches=false,确保 reduced-motion 不介入本用例
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    }))
    const target = ref(123)
    const display = useCountUp(target, {
      duration: 50,
      active: ref(false),
      holdWhenInactive: true,
    })
    await new Promise((r) => setTimeout(r, 80))
    // 关键断言:hold 模式下未激活 → 不跳 target,保持初值 0
    expect(display.value).toBe(0)
    expect(display.value).not.toBe(123)
  })

  it('holdWhenInactive=true 时 active 从 false→true 后,正常插值到 target', async () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    }))
    const target = ref(88)
    const active = ref(false)
    const display = useCountUp(target, {
      duration: 50,
      active,
      holdWhenInactive: true,
    })
    await new Promise((r) => setTimeout(r, 60))
    // 激活前:hold 在 0
    expect(display.value).toBe(0)
    // 滚入视口 → active=true,触发 count-up
    active.value = true
    await new Promise((r) => setTimeout(r, 200))
    expect(display.value).toBeCloseTo(88, 0)
  })
})
