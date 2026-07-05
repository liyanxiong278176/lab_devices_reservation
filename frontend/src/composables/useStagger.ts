import { type Ref } from 'vue'
import { useIntersectionObserver } from '@vueuse/core'

/**
 * useStagger:容器进入视口时,给内部 `[data-stagger]` 子元素按 index×delay
 * 设置 transitionDelay 并加 `stagger-in` class,实现错峰入场。
 *
 * 配合 _motion.scss:`[data-stagger]` 默认 opacity:0 + translateY(8px),
 * 加上 stagger-in 后过渡到 opacity:1 + translateY(0),delay 越大越晚入。
 *
 * 仅入场一次(首次进入视口后 stop 观察,避免重复触发/省性能)。
 *
 * @param containerRef 容器元素 ref
 * @param opts.delay 每个元素错峰间隔(ms),默认 60
 */
export interface UseStaggerOptions {
  delay?: number
}

// reduced-motion 命中判定(模式与 useCountUp 一致;SSR/无 matchMedia 环境返回 false)
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useStagger(
  containerRef: Ref<HTMLElement | null>,
  opts: UseStaggerOptions = {},
): void {
  const delay = opts.delay ?? 60

  const { stop } = useIntersectionObserver(
    containerRef,
    (entries) => {
      // reduced-motion 短路:命中则所有 [data-stagger] 子元素立即显现,停止观察(不错峰)
      if (prefersReducedMotion()) {
        const container = containerRef.value
        if (container) {
          container
            .querySelectorAll<HTMLElement>('[data-stagger]')
            .forEach((el) => el.classList.add('stagger-in'))
        }
        stop()
        return
      }
      const entry = entries[0]
      if (!entry?.isIntersecting) return
      const container = containerRef.value
      if (!container) return
      const items = container.querySelectorAll<HTMLElement>('[data-stagger]')
      items.forEach((el, i) => {
        el.style.transitionDelay = `${i * delay}ms`
        el.classList.add('stagger-in')
      })
      // 入场动画只触发一次,完成后停止观察
      stop()
    },
  )
}
