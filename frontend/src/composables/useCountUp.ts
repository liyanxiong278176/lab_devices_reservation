import { onScopeDispose, ref, watch, type Ref } from 'vue'

/**
 * useCountUp:数字滚动动画。
 *
 * 监听 target,当 target 变化(或首次激活)时,用 requestAnimationFrame + easeOutExpo
 * 从当前 display 值平滑插值到 target.value。命中 prefers-reduced-motion 或 active=false
 * 时直跳目标(无动画)。返回 display ref,模板里直接渲染。
 *
 * @param target 目标数值 ref
 * @param opts.duration 动画时长(ms),默认 1000
 * @param opts.active 是否激活(激活才动画),默认 ref(true)
 */
export interface UseCountUpOptions {
  duration?: number
  active?: Ref<boolean>
}

// easeOutExpo:快速冲近终点后减速收敛,数字滚动观感最自然。
const easeOutExpo = (t: number): number => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t))

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useCountUp(target: Ref<number>, opts: UseCountUpOptions = {}): Ref<number> {
  const duration = opts.duration ?? 1000
  const active = opts.active ?? ref(true)
  const display = ref(0)
  let rafId: number | null = null

  const cancel = () => {
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  const run = () => {
    cancel()
    // reduced-motion 命中 或 active=false:直跳目标,不动画(无障碍/省电)
    if (!active.value || prefersReducedMotion()) {
      display.value = target.value
      return
    }
    const from = display.value
    const to = target.value
    if (from === to) return
    const start = performance.now()
    const tick = () => {
      // 不信任 rAF 回调传入的 timestamp(jsdom 下与 performance.now() 不同源会负偏移),
      // 统一用 performance.now() 计算进度并夹紧到 [0,1]。
      const t = Math.max(0, Math.min(1, (performance.now() - start) / duration))
      display.value = from + (to - from) * easeOutExpo(t)
      if (t < 1) {
        rafId = requestAnimationFrame(tick)
      } else {
        rafId = null
      }
    }
    rafId = requestAnimationFrame(tick)
  }

  // immediate:首次挂载即触发(0 → target 的入场滚动)
  watch([target, active], run, { immediate: true })

  // 作用域销毁时取消未完成的 rAF,防内存泄漏
  onScopeDispose(cancel)

  return display
}
