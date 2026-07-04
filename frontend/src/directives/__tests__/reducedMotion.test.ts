import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, withDirectives } from 'vue'
import { mount } from '@vue/test-utils'
import { vReducedMotion } from '../reducedMotion'

function stubMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', () => ({
    matches,
    addEventListener() {},
    removeEventListener() {},
  }))
}

// 用 withDirectives 把指令挂到 vnode 上,绕开 runtime template 编译依赖
const Target = {
  render() {
    return withDirectives(h('div', { class: 'target' }), [[vReducedMotion]])
  },
}

describe('v-reduced-motion', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('prefers-reduced-motion 命中时,元素 animation/transition 设为 none(mounted)', () => {
    stubMatchMedia(true)
    const wrapper = mount(Target)
    const el = wrapper.find('.target').element as HTMLElement
    expect(el.style.animation).toBe('none')
    expect(el.style.transition).toBe('none')
  })

  it('未命中时不改 style', () => {
    stubMatchMedia(false)
    const el = document.createElement('div')
    ;(vReducedMotion as any).mounted?.(el, {})
    expect(el.style.animation).toBe('')
    expect(el.style.transition).toBe('')
  })

  it('updated hook 同样禁用动效', () => {
    stubMatchMedia(true)
    const el = document.createElement('div')
    ;(vReducedMotion as any).updated?.(el, {})
    expect(el.style.animation).toBe('none')
    expect(el.style.transition).toBe('none')
  })
})
