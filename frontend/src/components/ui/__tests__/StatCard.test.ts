import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StatCard from '../StatCard.vue'

/**
 * jsdom 不实现 IntersectionObserver,@vueuse/core 的 useIntersectionObserver
 * 内部 new IntersectionObserver 会丢 TypeError → 必须 stub(模式参考 useStagger.test.ts)。
 * StatCard 组件测只验渲染 + props 透传,不断言 count-up 数值(动画逻辑由 useCountUp 单测覆盖)。
 */
function stubIO() {
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(_cb: any) {}
      observe() {}
      unobserve() {}
      takeRecords() {
        return []
      }
      disconnect() {}
    },
  )
}

describe('StatCard', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('mount + {value, label} 渲染 label 文本 + 数字节点存在', () => {
    stubIO()
    const wrapper = mount(StatCard, {
      props: { value: 1280, label: '设备总数' },
    })
    expect(wrapper.text()).toContain('设备总数')
    // 数字节点存在(初始 display 由 useCountUp 决定,只验节点在)
    expect(wrapper.find('.stat-card__value').exists()).toBe(true)
  })

  it('unit="台" 渲染单位节点 + 文本含 "台"', () => {
    stubIO()
    const wrapper = mount(StatCard, {
      props: { value: 1280, label: '设备总数', unit: '台' },
    })
    expect(wrapper.find('.stat-card__unit').exists()).toBe(true)
    expect(wrapper.text()).toContain('台')
  })

  it('trend={delta:12,dir:"up"} 渲染 trend 节点 + 含 "12" + 含 up 状态类', () => {
    stubIO()
    const wrapper = mount(StatCard, {
      props: { value: 1280, label: '设备总数', trend: { delta: 12, dir: 'up' } },
    })
    const trend = wrapper.find('.stat-card__trend')
    expect(trend.exists()).toBe(true)
    expect(trend.classes()).toContain('stat-card__trend--up')
    expect(trend.text()).toContain('12')
  })

  it('trend={delta:5,dir:"down"} 渲染 down 状态类', () => {
    stubIO()
    const wrapper = mount(StatCard, {
      props: { value: 1280, label: '设备总数', trend: { delta: 5, dir: 'down' } },
    })
    const trend = wrapper.find('.stat-card__trend')
    expect(trend.classes()).toContain('stat-card__trend--down')
  })

  it('icon="Monitor" 渲染 icon chip 节点', () => {
    stubIO()
    const wrapper = mount(StatCard, {
      props: { value: 1280, label: '设备总数', icon: 'Monitor' },
    })
    expect(wrapper.find('.stat-card__icon').exists()).toBe(true)
  })
})
