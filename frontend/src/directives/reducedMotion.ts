import type { Directive } from 'vue'

/**
 * v-reduced-motion:命中 `prefers-reduced-motion: reduce` 时,强制禁用元素动效。
 *
 * 用法:`<div v-reduced-motion class="aurora-bg">` / `<Icon v-reduced-motion />`
 *
 * 无障碍:前庭功能障碍用户开启系统级"减少动效"后,任何 animation/transition 都
 * 可能引发不适。本指令在 mounted/updated 时检测 media query,命中即把元素的
 * animation 与 transition 置为 none。未命中(默认)不改 style,零成本。
 */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function apply(el: HTMLElement): void {
  if (!prefersReducedMotion()) return
  el.style.animation = 'none'
  el.style.transition = 'none'
}

export const vReducedMotion: Directive<HTMLElement> = {
  mounted(el) {
    apply(el)
  },
  updated(el) {
    // 元素后续可能被框架重新设了内联 style(如动态绑定),updated 复核一次
    apply(el)
  },
}
