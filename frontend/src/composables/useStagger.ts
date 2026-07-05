import { onScopeDispose, type Ref } from 'vue'
import { useIntersectionObserver } from '@vueuse/core'
import { useReducedMotion } from '@/utils/motion'

/**
 * useStagger:容器进入视口时,给内部 `[data-stagger]` 子元素按 index×delay
 * 设置 transitionDelay 并加 `stagger-in` class,实现错峰入场。
 *
 * 配合 _motion.scss:`[data-stagger]` 默认 opacity:0 + translateY(8px),
 * 加上 stagger-in 后过渡到 opacity:1 + translateY(0),delay 越大越晚入。
 *
 * 两段职责:
 *   1. 首屏入场(错峰动画):IntersectionObserver 监测容器入视口;容器在视口但
 *      async 数据未到(子节点还没渲染)时,挂一次性 MutationObserver 等子节点
 *      出现再 reveal。首屏 reveal 完成(entranceDone=true)后 IO/MO 停止。
 *   2. 后续渲染(筛选/翻页的新卡片):调用方在数据加载后调返回的 reveal() 即时
 *      显现(不错峰,翻页要快)。reveal() 在首屏入场未完成时会跳过,把首屏交给
 *      IO/MO(保留错峰动画)——调用方无需再维护 firstLoad 标志。
 *
 * @param containerRef 容器元素 ref
 * @param opts.delay 每个元素错峰间隔(ms),默认 60
 * @returns { reveal } reveal():后续渲染后即时显现新增的未入场 [data-stagger]
 */
export interface UseStaggerOptions {
  delay?: number
}

export function useStagger(
  containerRef: Ref<HTMLElement | null>,
  opts: UseStaggerOptions = {},
): { reveal: () => void } {
  const delay = opts.delay ?? 60
  const reduced = useReducedMotion()
  // 首屏错峰入场是否已完成。未完成时 reveal() 跳过,把首屏交给 IO/MO(保留动画)。
  let entranceDone = false
  let mo: MutationObserver | null = null

  // 首屏入场 reveal:带 index×delay 错峰;返回是否真的 reveal 了 ≥1 个。
  const revealStaggered = (container: HTMLElement): boolean => {
    const items = container.querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
    if (!items.length) return false
    items.forEach((el, i) => {
      el.style.transitionDelay = `${i * delay}ms`
      el.classList.add('stagger-in')
    })
    return true
  }

  // 调用方用的即时 reveal(后续渲染):无错峰延迟,翻页/筛选要快。
  // 首屏入场未完成时跳过,避免抢走 IO/MO 的错峰动画。
  const reveal = () => {
    if (!entranceDone) return
    const container = containerRef.value
    if (!container) return
    container
      .querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
      .forEach((el) => el.classList.add('stagger-in'))
  }

  const cleanup = () => {
    mo?.disconnect()
    mo = null
    stop()
  }

  // 容器已入视口但子节点未到:挂一次性 MO,子节点出现即错峰 reveal 并清理。
  // subtree:true 兼容 [data-stagger] 非直接子节点的视图;addedNodes 元素过滤
  // 跳过纯属性/文本变更(hover class、loading 遮罩文本等),减少无谓 querySelectorAll。
  const armFallback = (container: HTMLElement) => {
    if (mo) return
    mo = new MutationObserver((mutations) => {
      const addedElement = mutations.some((m) =>
        [...m.addedNodes].some((n) => n.nodeType === 1),
      )
      if (addedElement && revealStaggered(container)) {
        entranceDone = true
        cleanup()
      }
    })
    mo.observe(container, { childList: true, subtree: true })
  }

  const { stop } = useIntersectionObserver(
    containerRef,
    (entries) => {
      const container = containerRef.value
      if (!container) return
      // reduced-motion 短路:不论是否 intersecting,立即显现全部并停止。
      // 可见性由 _motion.scss 的 reduced-motion 全局守卫([data-stagger] opacity:1)兜底。
      if (reduced.value) {
        container
          .querySelectorAll<HTMLElement>('[data-stagger]:not(.stagger-in)')
          .forEach((el) => el.classList.add('stagger-in'))
        entranceDone = true
        cleanup()
        return
      }
      const entry = entries[0]
      if (!entry?.isIntersecting) return
      if (revealStaggered(container)) {
        entranceDone = true
        stop()
        return
      }
      // 容器在视口但暂无 [data-stagger] 子节点(async 数据竞态):等子节点出现。
      armFallback(container)
    },
  )

  onScopeDispose(cleanup)

  return { reveal }
}
