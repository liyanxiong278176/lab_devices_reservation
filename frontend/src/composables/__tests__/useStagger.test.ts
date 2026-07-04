import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { nextTick, ref } from 'vue'
import { useStagger } from '../useStagger'

/**
 * 捕获 @vueuse/core useIntersectionObserver 内部 new 出的 IntersectionObserver 回调,
 * 测试侧手动触发它(因为 jsdom 不实现 IntersectionObserver,必须 stub)。
 */
let ioCallback: ((entries: any[]) => void) | null = null
let disconnectSpy: Mock

function stubIO() {
  ioCallback = null
  disconnectSpy = vi.fn()
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(cb: any) {
        ioCallback = cb
      }
      observe() {}
      unobserve() {}
      takeRecords() {
        return []
      }
      disconnect() {
        disconnectSpy()
      }
    },
  )
}

describe('useStagger', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    ioCallback = null
  })

  it('容器进入视口时,子元素按 index×delay 设置 transitionDelay 并加 stagger-in class', async () => {
    stubIO()
    const container = document.createElement('div')
    const children = [0, 1, 2].map(() => {
      const el = document.createElement('div')
      el.setAttribute('data-stagger', '')
      container.appendChild(el)
      return el
    })
    document.body.appendChild(container)

    useStagger(ref(container), { delay: 60 })
    await nextTick()
    // 模拟进入视口
    ioCallback!([{ isIntersecting: true, target: container }])
    await nextTick()

    expect(children[0].style.transitionDelay).toBe('0ms')
    expect(children[1].style.transitionDelay).toBe('60ms')
    expect(children[2].style.transitionDelay).toBe('120ms')
    expect(children[0].classList.contains('stagger-in')).toBe(true)
    expect(children[2].classList.contains('stagger-in')).toBe(true)
  })

  it('未进入视口时不加 stagger-in', async () => {
    stubIO()
    const container = document.createElement('div')
    const el = document.createElement('div')
    el.setAttribute('data-stagger', '')
    container.appendChild(el)
    document.body.appendChild(container)

    useStagger(ref(container), { delay: 60 })
    await nextTick()
    ioCallback!([{ isIntersecting: false, target: container }])
    await nextTick()

    expect(el.classList.contains('stagger-in')).toBe(false)
    expect(el.style.transitionDelay).toBe('')
  })

  it('仅触发一次(入场后 disconnect 停止观察)', async () => {
    stubIO()
    const container = document.createElement('div')
    const el = document.createElement('div')
    el.setAttribute('data-stagger', '')
    container.appendChild(el)

    useStagger(ref(container), { delay: 60 })
    await nextTick()
    expect(disconnectSpy).not.toHaveBeenCalled()
    ioCallback!([{ isIntersecting: true, target: container }])
    await nextTick()
    // stop() 内部调用 observer.disconnect(),真实环境下即不再回调
    expect(disconnectSpy).toHaveBeenCalled()
  })
})
