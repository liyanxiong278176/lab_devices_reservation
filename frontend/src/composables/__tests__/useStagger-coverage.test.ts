import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'

const motion = vi.hoisted(() => ({ reduced: { value: false } }))
vi.mock('@/utils/motion', () => ({ useReducedMotion: () => motion.reduced }))

import { useStagger } from '../useStagger'

let callback: ((entries: Array<{ isIntersecting: boolean }>) => void) | undefined
let disconnectSpy: Mock
let scope: EffectScope | undefined

function setupObserver() {
  callback = undefined
  disconnectSpy = vi.fn()
  vi.stubGlobal('IntersectionObserver', class {
    constructor(cb: (entries: Array<{ isIntersecting: boolean }>) => void) { callback = cb }
    observe() {}
    unobserve() {}
    takeRecords() { return [] }
    disconnect() { disconnectSpy() }
  })
}

function addItem(container: HTMLElement, className = '') {
  const element = document.createElement('div')
  element.setAttribute('data-stagger', '')
  if (className) element.className = className
  container.append(element)
  return element
}

afterEach(() => {
  scope?.stop()
  scope = undefined
  callback = undefined
  motion.reduced.value = false
  vi.unstubAllGlobals()
})

describe('useStagger uncovered lifecycle paths', () => {
  it('ignores empty observer batches and missing containers, then reveals later items immediately', async () => {
    setupObserver()
    const container = document.createElement('div')
    const containerRef = ref<HTMLElement | null>(container)
    scope = effectScope()
    let reveal!: () => void
    scope.run(() => { reveal = useStagger(containerRef).reveal })
    await nextTick()

    reveal()
    callback?.([])
    callback?.([{ isIntersecting: true }])
    callback?.([{ isIntersecting: true }])
    expect(container.querySelector('[data-stagger]')).toBeNull()

    const first = addItem(container)
    callback?.([{ isIntersecting: true }])
    expect(first.classList.contains('stagger-in')).toBe(true)
    expect(first.style.transitionDelay).toBe('0ms')

    const later = addItem(container)
    reveal()
    expect(later.classList.contains('stagger-in')).toBe(true)
    expect(later.style.transitionDelay).toBe('')

    containerRef.value = null
    reveal()
    callback?.([{ isIntersecting: true }])
    expect(disconnectSpy).toHaveBeenCalled()
  })

  it('waits for element mutations after intersection but ignores text-only mutations', async () => {
    setupObserver()
    const container = document.createElement('div')
    document.body.append(container)
    scope = effectScope()
    scope.run(() => useStagger(ref(container), { delay: 25 }))
    await nextTick()

    callback?.([{ isIntersecting: true }])
    container.append(document.createTextNode('loading'))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container.querySelector('[data-stagger]')).toBeNull()
    expect(disconnectSpy).not.toHaveBeenCalled()

    const appeared = addItem(container)
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(appeared.classList.contains('stagger-in')).toBe(true)
    expect(appeared.style.transitionDelay).toBe('0ms')
    expect(disconnectSpy).toHaveBeenCalled()
    container.remove()
  })

  it('reveals immediately under reduced motion and disconnects regardless of intersection state', async () => {
    setupObserver()
    motion.reduced.value = true
    const container = document.createElement('div')
    const item = addItem(container)
    const containerRef = ref<HTMLElement | null>(container)
    scope = effectScope()
    scope.run(() => useStagger(containerRef))
    await nextTick()

    callback?.([{ isIntersecting: false }])
    expect(item.classList.contains('stagger-in')).toBe(true)
    expect(item.style.transitionDelay).toBe('')
    expect(disconnectSpy).toHaveBeenCalled()
  })
})
