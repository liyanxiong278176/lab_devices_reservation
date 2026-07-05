import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusDot from '../StatusDot.vue'

describe('StatusDot', () => {
  it('IN_USE 渲染"使用中"文字 + 含 in-use 状态类 + data-status', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'IN_USE', label: true },
    })
    expect(wrapper.classes()).toContain('status-dot--in-use')
    expect(wrapper.attributes('data-status')).toBe('IN_USE')
    expect(wrapper.text()).toContain('使用中')
  })

  it('IDLE + label 渲染"空闲"', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'IDLE', label: true },
    })
    expect(wrapper.text()).toContain('空闲')
  })

  it('MAINTENANCE + label 渲染"维护中"', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'MAINTENANCE', label: true },
    })
    expect(wrapper.text()).toContain('维护中')
  })

  it('BROKEN 渲染"故障"文字 + 含 broken 状态类', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'BROKEN', label: true },
    })
    expect(wrapper.classes()).toContain('status-dot--broken')
    expect(wrapper.text()).toContain('故障')
  })

  it('label=false(默认)不渲染文字节点(只有点)', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'IDLE' },
    })
    expect(wrapper.find('.status-dot__label').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('size=12 时点元素宽高反映尺寸', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'IN_USE', size: 12 },
    })
    const dot = wrapper.find('.status-dot__dot')
    expect(dot.exists()).toBe(true)
    const el = dot.element as HTMLElement
    expect(el.style.width).toBe('12px')
    expect(el.style.height).toBe('12px')
  })

  it('labelText 覆盖默认文字', () => {
    const wrapper = mount(StatusDot, {
      props: { status: 'IDLE', label: true, labelText: '设备可用' },
    })
    expect(wrapper.text()).toContain('设备可用')
    expect(wrapper.text()).not.toContain('空闲')
  })
})
