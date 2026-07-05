import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SegmentedControl from '../SegmentedControl.vue'

/**
 * SegmentedControl — 段控件(底槽 pill + 跟随选中项的青色滑块)
 * 滑块用 CSS Grid 等宽 + transform 百分比方案(`translateX(calc(var(--i) * 100%))`),
 * jsdom 不做真 layout(offsetLeft=0),所以测 --i CSS 变量与 data-active 标记,
 * 而不是 px 测量。
 */

const OPTS = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
  { value: 'c', label: 'C' },
]

describe('SegmentedControl', () => {
  it('mount + modelValue="a" 渲染全部 options 文本', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    expect(wrapper.text()).toContain('A')
    expect(wrapper.text()).toContain('B')
    expect(wrapper.text()).toContain('C')
  })

  it('modelValue="a" → 值=a 的选项带 active 标记(data-active)', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    const active = wrapper.find('[data-active="true"]')
    expect(active.exists()).toBe(true)
    expect(active.text()).toBe('A')
  })

  it('点击第二项 → emit update:modelValue payload "b"', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['b'])
  })

  it('disabled 选项点击不 emit', async () => {
    const opts = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B', disabled: true },
    ]
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: opts },
    })
    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('受控更新:父改 modelValue="b" → active 标记移到第二项', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    await wrapper.setProps({ modelValue: 'b' })
    const active = wrapper.find('[data-active="true"]')
    expect(active.exists()).toBe(true)
    expect(active.text()).toBe('B')
  })

  it('滑块元素存在 + --i 反映选中 index', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'b', options: OPTS },
    })
    const slider = wrapper.find('.segmented__slider')
    expect(slider.exists()).toBe(true)
    // b 是第 1 项(0-based index=1)
    const i = (slider.element as HTMLElement).style.getPropertyValue('--i')
    expect(i.trim()).toBe('1')
  })

  it('受控更新:--i 跟随 modelValue 变化', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    await wrapper.setProps({ modelValue: 'c' })
    const slider = wrapper.find('.segmented__slider')
    const i = (slider.element as HTMLElement).style.getPropertyValue('--i')
    expect(i.trim()).toBe('2')
  })

  it('number 值也能工作:modelValue=1 选中第二项', () => {
    const opts = [
      { value: 0, label: '零' },
      { value: 1, label: '壹' },
    ]
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 1, options: opts },
    })
    const active = wrapper.find('[data-active="true"]')
    expect(active.text()).toBe('壹')
  })

  it('icon 选项渲染 icon 节点', () => {
    const wrapper = mount(SegmentedControl, {
      props: {
        modelValue: 'a',
        options: [
          { value: 'a', label: 'A', icon: 'Monitor' },
          { value: 'b', label: 'B' },
        ],
      },
    })
    expect(wrapper.find('.segmented__icon').exists()).toBe(true)
  })
})
