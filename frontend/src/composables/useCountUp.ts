import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { useReducedMotion } from '@/utils/motion'

/**
 * useCountUp:数字滚动动画。
 *
 * 监听 target/active/reduced-motion,变化时用 requestAnimationFrame + easeOutExpo
 * 从当前 display 值平滑插值到 target.value。
 *   - 命中 prefers-reduced-motion(初次渲染时)=true 时直跳 target(无障碍)。
 *   - OS 在会话中途把 reduce-motion 从 OFF→ON:cancel 当前 rAF,display 直接跳 target。
 *     (OS 切换 OFF→ON 是用户主动表态"我现在需要静",不能让他等动画播完。)
 *   - OS 切换 ON→OFF 不主动回退(少做少错),下一次 target/active 变化会按 OFF 重新评估。
 *   - active=false 时:默认直跳 target(向后兼容);
 *     holdWhenInactive=true 则保持当前 display(配合 IntersectionObserver 做
 *     "滚入视口才 count-up" 入场动效——未入视口前 hold 在 0,避免一上来就跳终点
 *     导致激活时 from===to 无动画可播)。返回 display ref 供模板直接渲染。
 *
 * @param target 目标数值 ref
 * @param opts.duration 动画时长(ms),默认 1000
 * @param opts.active 是否激活(激活才动画),默认 ref(true)
 * @param opts.holdWhenInactive active=false 时是否保持当前 display(默认 false=直跳 target)
 */
export interface UseCountUpOptions {
  duration?: number
  active?: Ref<boolean>
  /** active=false 时保持当前 display 不跳 target(默认 false,向后兼容)。StatCard 入场用 true。 */
  holdWhenInactive?: boolean
}

// easeOutExpo:快速冲近终点后减速收敛,数字滚动观感最自然。
const easeOutExpo = (t: number): number => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t))

export function useCountUp(target: Ref<number>, opts: UseCountUpOptions = {}): Ref<number> {
  const duration = opts.duration ?? 1000
  const active = opts.active ?? ref(true)
  const holdWhenInactive = opts.holdWhenInactive ?? false
  const display = ref(0)
  const reduced = useReducedMotion()
  let rafId: number | null = null

  const cancel = () => {
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  // OS 把 reduce-motion 切到 ON:无障碍优先 — 取消未完成的 rAF,display 直接跳 target。
  // 这是用户主动表态"现在不需要动画",不等当前动画播完。
  watch(reduced, (now, was) => {
    if (now && !was) {
      cancel()
      display.value = target.value
    }
  })

  const run = () => {
    cancel()
    // reduced-motion 命中(无障碍):永远直跳 target,优先级最高
    if (reduced.value) {
      display.value = target.value
      return
    }
    // 未激活:默认直跳 target(向后兼容);holdWhenInactive=true 则保持当前 display
    // (StatCard 入场:未滚入视口前 hold 在 0,滚入后 active=true 才走 count-up)
    if (!active.value) {
      if (!holdWhenInactive) {
        display.value = target.value
      }
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

  // immediate:首次挂载即触发(0 → target 的入场滚动)。
  // reduced 入 watch deps:会话中途 OS 切换也会重新评估(无障碍 catch-up)。
  watch([target, active, reduced], run, { immediate: true })

  // 作用域销毁时取消未完成的 rAF,防内存泄漏
  onScopeDispose(cancel)

  return display
}
