import { ref, type Ref } from 'vue'

/**
 * prefers-reduced-motion 判定与响应式订阅(共享单源)。
 *
 * 设计要点:
 *   - SSR / 无 matchMedia 环境(jsdom 默认、Node SSR)返回 false。
 *   - 提供一次性查询 `prefersReducedMotion()` 供非响应式场景(SSR 守卫、初始化期决策)
 *     与响应式订阅 `useReducedMotion()` 供 Vue watcher / computed。
 *   - 单一全局 Ref,所有调用方看到一致的当前值;OS 层媒体查询变化时通过
 *     `MediaQueryList.change` 事件推送,useCountUp / 任何 watch deps 自动重算。
 *   - 识别 matchMedia 身份变化并重绑:正常浏览器 matchMedia 对同一 query 返回稳定
 *     MediaQueryList 引用,身份不变就只绑一次;vi.stubGlobal 等测试桩在每次
 *     stubGlobal('matchMedia', ...) 时把全局替换成新函数,旧 MediaQueryList 引用
 *     不再代表当前 OS 偏好——检测到身份变化就 removeEventListener 旧的、bind 新的。
 */

const _reduced = ref(false) // module-level singleton,所有 caller 共享
let _boundMql: MediaQueryList | null = null
let _boundOnChange: ((e: MediaQueryListEvent) => void) | null = null

function bindMediaQuery() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
  // 同一 MediaQueryList 实例 → 已绑,跳过
  if (_boundMql === mql) return

  // 解绑旧的(测试桩切换 matchMedia 实现时,旧引用已不代表真实 OS 偏好,必须摘掉)
  if (_boundMql && _boundOnChange) {
    _boundMql.removeEventListener?.('change', _boundOnChange)
  }
  _boundMql = mql
  _reduced.value = mql.matches
  _boundOnChange = (e: MediaQueryListEvent) => {
    _reduced.value = e.matches
  }
  // 标准 addEventListener;不支持的旧环境(stub 漏了)静默失败——initial reads 仍生效。
  _boundMql.addEventListener?.('change', _boundOnChange)
}

/**
 * 一次性查询(SSR-safe)。Vue 模板/watch 不应使用,改用 `useReducedMotion`。
 * 保留它是因为有非响应式初始化路径(如 IO 回调一拍即用的快照读取)。
 */
export function prefersReducedMotion(): boolean {
  bindMediaQuery()
  return _reduced.value
}

/**
 * 响应式订阅。返回的 Ref 在 OS 层切换"减少动效"时自动更新,
 * watch deps 把它加入即可在会话中途响应变化(useCountUp 用法)。
 */
export function useReducedMotion(): Ref<boolean> {
  bindMediaQuery()
  return _reduced
}
